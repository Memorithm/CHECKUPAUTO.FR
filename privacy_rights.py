from __future__ import annotations

import datetime
import hashlib
import json
import os
import sqlite3
from pathlib import Path

import booking_bridge
import compliance_operations
import compliance_store
import mercure_admin_client as mercure
import mobile_devices
import notification_broker
import privacy_suppression as suppression
import reminder_dispatch
import review_followup


REQUEST_PURPOSES = {
    "all_processing",
    "direct_marketing",
    "review_request",
    "reminders",
}
MANUAL_STATES = {"manual_required", "failed"}
ERASABLE_NOTIFICATION_CATEGORIES = {
    "ct_due_reminder",
    "google_review",
    "direct_marketing_email",
    "direct_marketing_sms",
    "direct_marketing_push",
}


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _private_dir() -> Path:
    return Path(os.environ.get("CYBERCHECK_PRIVATE_DIR", "/root/CyberCheckPrivate"))


def _vault_path() -> Path:
    return _private_dir() / "rights-locator-vault.sqlite3"


def _vault_connect() -> sqlite3.Connection:
    path = _vault_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except PermissionError:
        pass
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    return db


def init_db(db_path: Path | str | None = None) -> None:
    compliance_store.init_db(db_path)
    compliance_operations.init_db(db_path)
    suppression.init_db(db_path)
    with compliance_store.connect(db_path) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS rights_execution_steps(
              request_id TEXT NOT NULL,
              store_name TEXT NOT NULL,
              action TEXT NOT NULL,
              status TEXT NOT NULL,
              affected_count INTEGER NOT NULL DEFAULT 0,
              detail_code TEXT NOT NULL DEFAULT '',
              evidence_hash TEXT NOT NULL DEFAULT '',
              updated_at TEXT NOT NULL,
              PRIMARY KEY(request_id,store_name,action)
            );
            CREATE INDEX IF NOT EXISTS idx_rights_execution_status
              ON rights_execution_steps(status,updated_at);
            """
        )
    with _vault_connect() as vault:
        vault.executescript(
            """
            CREATE TABLE IF NOT EXISTS rights_locator(
              request_id TEXT PRIMARY KEY,
              subject_kind TEXT NOT NULL,
              subject_ref TEXT NOT NULL,
              purpose TEXT NOT NULL,
              rectification_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            """
        )
    try:
        _vault_path().chmod(0o600)
    except PermissionError:
        pass


def _request_row(request_id: object, db_path: Path | str | None = None) -> sqlite3.Row:
    clean = str(request_id or "").strip().lower()
    if len(clean) != 32 or any(ch not in "0123456789abcdef" for ch in clean):
        raise ValueError("requestId invalide")
    init_db(db_path)
    with compliance_store.connect(db_path) as db:
        row = db.execute(
            "SELECT * FROM rights_requests WHERE request_id=?",
            (clean,),
        ).fetchone()
    if row is None:
        raise LookupError("demande inconnue")
    return row


def _locator(request_id: object) -> dict:
    clean = str(request_id or "").strip().lower()
    with _vault_connect() as db:
        row = db.execute(
            "SELECT * FROM rights_locator WHERE request_id=?",
            (clean,),
        ).fetchone()
    if row is None:
        raise RuntimeError("locator_not_available")
    return {
        "requestId": clean,
        "subjectKind": str(row["subject_kind"]),
        "subjectRef": str(row["subject_ref"]),
        "purpose": str(row["purpose"]),
        "rectification": json.loads(row["rectification_json"] or "{}"),
    }


def _clear_locator(request_id: str) -> None:
    with _vault_connect() as db:
        db.execute("DELETE FROM rights_locator WHERE request_id=?", (request_id,))


def create_request(payload: dict, db_path: Path | str | None = None) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("demande invalide")
    request_type = str(payload.get("type") or "").strip()
    if request_type not in compliance_store.RIGHT_TYPES:
        raise ValueError("type de droit invalide")
    kind, subject_ref = suppression.normalize(payload.get("subjectKind"), payload.get("subjectRef"))
    purpose = str(payload.get("purpose") or "all_processing").strip()
    if purpose not in REQUEST_PURPOSES:
        raise ValueError("finalité de droit invalide")
    if request_type not in {"objection", "consent_withdrawal"}:
        purpose = "all_processing"
    elif request_type == "consent_withdrawal" and purpose not in {"direct_marketing", "review_request"}:
        raise ValueError("le retrait du consentement doit viser un traitement fondé sur le consentement")
    rectification = payload.get("rectification") or {}
    if not isinstance(rectification, dict) or len(rectification) > 20:
        raise ValueError("rectification invalide")
    for key, value in rectification.items():
        if len(str(key)) > 80 or len(str(value)) > 1000:
            raise ValueError("rectification invalide")

    request = compliance_store.create_rights_request_hashed(
        request_type,
        suppression.identity_hash(kind, subject_ref),
        notes=str(payload.get("notes") or ""),
        db_path=db_path,
    )
    stamp = _now_iso()
    init_db(db_path)
    try:
        with _vault_connect() as vault:
            vault.execute(
                """INSERT INTO rights_locator(
                     request_id,subject_kind,subject_ref,purpose,rectification_json,created_at,updated_at
                   ) VALUES(?,?,?,?,?,?,?)""",
                (
                    request["id"],
                    kind,
                    subject_ref,
                    purpose,
                    json.dumps(rectification, ensure_ascii=False, sort_keys=True),
                    stamp,
                    stamp,
                ),
            )
    except Exception:
        with compliance_store.connect(db_path) as db:
            db.execute("DELETE FROM rights_requests WHERE request_id=?", (request["id"],))
        raise
    return {**request, "subjectKind": kind, "purpose": purpose, "locatorAvailable": True}


def _record_step(
    request_id: str,
    store: str,
    action: str,
    status: str,
    *,
    count: int = 0,
    detail: str = "",
    evidence: dict | None = None,
    db_path: Path | str | None = None,
) -> dict:
    if status not in {"applied", "retained", "not_applicable", "manual_required", "failed"}:
        raise ValueError("statut étape invalide")
    safe_store = str(store or "").strip()[:80]
    safe_action = str(action or "").strip()[:80]
    safe_detail = str(detail or "").strip()[:120]
    if not safe_store or not safe_action:
        raise ValueError("étape invalide")
    with compliance_store.connect(db_path) as db:
        existing = db.execute(
            """SELECT status,affected_count,detail_code,evidence_hash,updated_at
               FROM rights_execution_steps
               WHERE request_id=? AND store_name=? AND action=?""",
            (request_id, safe_store, safe_action),
        ).fetchone()
    if existing and existing["status"] == "applied" and status == "manual_required":
        return {
            "store": safe_store,
            "action": safe_action,
            "status": "applied",
            "affectedCount": int(existing["affected_count"]),
            "detailCode": existing["detail_code"],
            "evidenceHash": existing["evidence_hash"],
        }
    evidence = dict(evidence or {})
    evidence.update(
        {
            "requestId": request_id,
            "store": safe_store,
            "action": safe_action,
            "status": status,
            "affectedCount": max(0, int(count)),
            "detailCode": safe_detail,
        }
    )
    audit = compliance_operations.record_audit_evidence(
        "rights_request",
        request_id,
        f"{safe_store}:{safe_action}",
        evidence,
        db_path,
    )
    with compliance_store.connect(db_path) as db:
        db.execute(
            """INSERT INTO rights_execution_steps(
                 request_id,store_name,action,status,affected_count,detail_code,evidence_hash,updated_at
               ) VALUES(?,?,?,?,?,?,?,?)
               ON CONFLICT(request_id,store_name,action) DO UPDATE SET
                 status=excluded.status,affected_count=excluded.affected_count,
                 detail_code=excluded.detail_code,evidence_hash=excluded.evidence_hash,
                 updated_at=excluded.updated_at""",
            (
                request_id,
                safe_store,
                safe_action,
                status,
                max(0, int(count)),
                safe_detail,
                audit["evidenceHash"],
                audit["createdAt"],
            ),
        )
    return {
        "store": safe_store,
        "action": safe_action,
        "status": status,
        "affectedCount": max(0, int(count)),
        "detailCode": safe_detail,
        "evidenceHash": audit["evidenceHash"],
    }


def steps(request_id: object, db_path: Path | str | None = None) -> list[dict]:
    row = _request_row(request_id, db_path)
    with compliance_store.connect(db_path) as db:
        rows = db.execute(
            """SELECT store_name,action,status,affected_count,detail_code,evidence_hash,updated_at
               FROM rights_execution_steps WHERE request_id=?
               ORDER BY store_name,action""",
            (row["request_id"],),
        ).fetchall()
    return [
        {
            "store": item["store_name"],
            "action": item["action"],
            "status": item["status"],
            "affectedCount": int(item["affected_count"]),
            "detailCode": item["detail_code"],
            "evidenceHash": item["evidence_hash"],
            "updatedAt": item["updated_at"],
        }
        for item in rows
    ]


def _reminder_rows(kind: str, ref: str) -> list[dict]:
    if kind not in {"mercure_account", "mercure_free", "vehicle", "contract"}:
        return []
    reminder_dispatch.init_db()
    if kind == "mercure_account":
        where, args = "client_kind='account' AND client_id=?", (ref,)
    elif kind == "mercure_free":
        where, args = "client_kind='free' AND client_id=?", (ref,)
    elif kind == "vehicle":
        where, args = "vehicle_id=?", (ref,)
    elif kind == "contract":
        where, args = "appointment_id=?", (ref,)
    else:
        return []
    with reminder_dispatch.connect() as db:
        rows = db.execute(
            f"""SELECT vehicle_id,client_kind,client_id,due_date,appointment_id,
                       first_seen_at,last_seen_at,quarantined
                FROM reminder_target WHERE {where}""",
            args,
        ).fetchall()
    return [
        {
            "vehicleId": row["vehicle_id"],
            "clientKind": row["client_kind"],
            "clientId": row["client_id"],
            "dueDate": row["due_date"],
            "appointmentId": row["appointment_id"],
            "firstSeenAt": row["first_seen_at"],
            "lastSeenAt": row["last_seen_at"],
            "quarantined": bool(row["quarantined"]),
        }
        for row in rows
    ]


def _reminder_delete(kind: str, ref: str) -> int:
    if kind not in {"mercure_account", "mercure_free", "vehicle", "contract"}:
        return 0
    reminder_dispatch.init_db()
    if kind == "mercure_account":
        where, args = "client_kind='account' AND client_id=?", (ref,)
    elif kind == "mercure_free":
        where, args = "client_kind='free' AND client_id=?", (ref,)
    elif kind == "vehicle":
        where, args = "vehicle_id=?", (ref,)
    elif kind == "contract":
        where, args = "appointment_id=?", (ref,)
    else:
        return 0
    with reminder_dispatch.connect() as db:
        cursor = db.execute(f"DELETE FROM reminder_target WHERE {where}", args)
    return int(cursor.rowcount or 0)


def _reminder_quarantine(kind: str, ref: str) -> int:
    if kind not in {"mercure_account", "mercure_free", "vehicle", "contract"}:
        return 0
    reminder_dispatch.init_db()
    if kind == "mercure_account":
        where, args = "client_kind='account' AND client_id=?", (ref,)
    elif kind == "mercure_free":
        where, args = "client_kind='free' AND client_id=?", (ref,)
    elif kind == "vehicle":
        where, args = "vehicle_id=?", (ref,)
    elif kind == "contract":
        where, args = "appointment_id=?", (ref,)
    else:
        return 0
    with reminder_dispatch.connect() as db:
        cursor = db.execute(
            f"UPDATE reminder_target SET quarantined=1 WHERE {where}",
            args,
        )
    return int(cursor.rowcount or 0)


def _mobile_installations(kind: str, ref: str) -> list[str]:
    if kind not in {"installation", "mercure_account", "mercure_free", "vehicle"}:
        return []
    mobile_devices.init_db()
    with mobile_devices.connect() as db:
        if kind == "installation":
            rows = db.execute(
                "SELECT installation_id FROM mobile_device WHERE installation_id=?",
                (ref.lower(),),
            ).fetchall()
        elif kind == "mercure_account":
            rows = db.execute(
                """SELECT DISTINCT installation_id FROM mobile_vehicle_binding
                   WHERE client_kind='account' AND client_id=?""",
                (ref,),
            ).fetchall()
        elif kind == "mercure_free":
            rows = db.execute(
                """SELECT DISTINCT installation_id FROM mobile_vehicle_binding
                   WHERE client_kind='free' AND client_id=?""",
                (ref,),
            ).fetchall()
        elif kind == "vehicle":
            rows = db.execute(
                "SELECT DISTINCT installation_id FROM mobile_vehicle_binding WHERE vehicle_id=?",
                (ref,),
            ).fetchall()
        else:
            rows = []
    return [str(row["installation_id"]) for row in rows]


def _mobile_rows(kind: str, ref: str) -> list[dict]:
    installations = _mobile_installations(kind, ref)
    if not installations:
        return []
    placeholders = ",".join("?" for _ in installations)
    with mobile_devices.connect() as db:
        rows = db.execute(
            f"""SELECT m.installation_id,m.token_hash,m.environment,m.created_at,m.updated_at,
                       m.last_seen_at,m.disabled_at,m.disabled_reason,
                       b.binding_id,b.vehicle_id,b.client_kind,b.client_id
                FROM mobile_device m
                LEFT JOIN mobile_vehicle_binding b ON b.installation_id=m.installation_id
                WHERE m.installation_id IN ({placeholders})
                ORDER BY m.installation_id,b.binding_id""",
            tuple(installations),
        ).fetchall()
    return [
        {
            "installationId": row["installation_id"],
            "deviceTokenHash": row["token_hash"],
            "environment": row["environment"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
            "lastSeenAt": row["last_seen_at"],
            "disabledAt": row["disabled_at"],
            "disabledReason": row["disabled_reason"],
            "bindingId": row["binding_id"],
            "vehicleId": row["vehicle_id"],
            "clientKind": row["client_kind"],
            "clientId": row["client_id"],
        }
        for row in rows
    ]


def _mobile_delete(kind: str, ref: str) -> int:
    installations = _mobile_installations(kind, ref)
    if not installations:
        return 0
    removed = 0
    with mobile_devices.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if kind == "installation":
            selected = installations
            for installation in selected:
                removed += int(
                    db.execute(
                        "DELETE FROM mobile_deadline WHERE installation_id=?",
                        (installation,),
                    ).rowcount
                    or 0
                )
                removed += int(
                    db.execute(
                        "DELETE FROM mobile_vehicle_binding WHERE installation_id=?",
                        (installation,),
                    ).rowcount
                    or 0
                )
                removed += int(
                    db.execute(
                        "DELETE FROM mobile_device WHERE installation_id=?",
                        (installation,),
                    ).rowcount
                    or 0
                )
            return removed

        if kind == "mercure_account":
            cursor = db.execute(
                "DELETE FROM mobile_vehicle_binding WHERE client_kind='account' AND client_id=?",
                (ref,),
            )
        elif kind == "mercure_free":
            cursor = db.execute(
                "DELETE FROM mobile_vehicle_binding WHERE client_kind='free' AND client_id=?",
                (ref,),
            )
        elif kind == "vehicle":
            cursor = db.execute(
                "DELETE FROM mobile_vehicle_binding WHERE vehicle_id=?",
                (ref,),
            )
        else:
            return 0
        removed += int(cursor.rowcount or 0)
        for installation in installations:
            remaining = int(
                db.execute(
                    "SELECT COUNT(*) n FROM mobile_vehicle_binding WHERE installation_id=?",
                    (installation,),
                ).fetchone()["n"]
            )
            if remaining == 0:
                removed += int(
                    db.execute(
                        "DELETE FROM mobile_deadline WHERE installation_id=?",
                        (installation,),
                    ).rowcount
                    or 0
                )
                removed += int(
                    db.execute(
                        "DELETE FROM mobile_device WHERE installation_id=?",
                        (installation,),
                    ).rowcount
                    or 0
                )
    return removed


def _notification_rows(kind: str, ref: str) -> list[dict]:
    if kind != "email":
        return []
    digest = hashlib.sha256(ref.strip().lower().encode("utf-8")).hexdigest()
    notification_broker.init_db()
    with notification_broker.connect() as db:
        rows = db.execute(
            """SELECT channel,category,reference,status,attempts,created_at,last_attempt_at,sent_at
               FROM notification_delivery WHERE recipient_hash=?
               ORDER BY created_at""",
            (digest,),
        ).fetchall()
    return [
        {
            "channel": row["channel"],
            "category": row["category"],
            "reference": row["reference"],
            "status": row["status"],
            "attempts": int(row["attempts"]),
            "createdAt": row["created_at"],
            "lastAttemptAt": row["last_attempt_at"],
            "sentAt": row["sent_at"],
        }
        for row in rows
    ]


def _notification_delete(kind: str, ref: str) -> int:
    if kind != "email":
        return 0
    digest = hashlib.sha256(ref.strip().lower().encode("utf-8")).hexdigest()
    notification_broker.init_db()
    categories = tuple(sorted(ERASABLE_NOTIFICATION_CATEGORIES))
    placeholders = ",".join("?" for _ in categories)
    with notification_broker.connect() as db:
        cursor = db.execute(
            f"""DELETE FROM notification_delivery
                WHERE recipient_hash=? AND category IN ({placeholders})""",
            (digest, *categories),
        )
    return int(cursor.rowcount or 0)


def _review_rows(kind: str, ref: str) -> list[dict]:
    if kind != "contract":
        return []
    review_followup.init_db()
    with review_followup.connect() as db:
        rows = db.execute(
            """SELECT appointment_id,status,attempts,first_seen_at,last_attempt_at,sent_at
               FROM review_followup WHERE appointment_id=?""",
            (ref,),
        ).fetchall()
    return [dict(row) for row in rows]


def _review_delete(kind: str, ref: str) -> int:
    if kind != "contract":
        return 0
    review_followup.init_db()
    with review_followup.connect() as db:
        cursor = db.execute("DELETE FROM review_followup WHERE appointment_id=?", (ref,))
    return int(cursor.rowcount or 0)


def _booking_rows(kind: str, ref: str) -> list[dict]:
    if kind != "contract":
        return []
    booking_bridge.init_db()
    with booking_bridge.analytics.connect() as db:
        rows = db.execute(
            """SELECT provider,external_id,status,first_seen_at,updated_at,confirmed_at,
                      appointment_at,amount_cents,service,source,campaign,device
               FROM booking_conversions WHERE external_id=?""",
            (ref,),
        ).fetchall()
    return [dict(row) for row in rows]


def _compliance_contract_rows(kind: str, ref: str, db_path: Path | str | None) -> dict:
    if kind != "contract":
        return {"consentReceipts": [], "withdrawalRequests": []}
    compliance_store.init_db(db_path)
    with compliance_store.connect(db_path) as db:
        receipts = [
            dict(row)
            for row in db.execute(
                """SELECT receipt_id,contract_ref,purpose,document_type,document_version,
                          content_hash,accepted_at,immediate_performance,source
                   FROM consent_receipts WHERE contract_ref=?""",
                (ref,),
            )
        ]
        withdrawal = []
        try:
            withdrawal = [
                {
                    "requestId": row["request_id"],
                    "submittedAt": row["submitted_at"],
                    "declarationHash": row["declaration_hash"],
                    "receiptStatus": row["receipt_status"],
                    "receiptSentAt": row["receipt_sent_at"],
                }
                for row in db.execute(
                    """SELECT request_id,submitted_at,declaration_hash,receipt_status,receipt_sent_at
                       FROM withdrawal_requests WHERE contract_ref=?""",
                    (ref,),
                )
            ]
        except sqlite3.OperationalError:
            pass
    for item in receipts:
        item["immediate_performance"] = bool(item["immediate_performance"])
    return {"consentReceipts": receipts, "withdrawalRequests": withdrawal}


def _mercure_snapshot(kind: str, ref: str) -> dict | None:
    if kind == "mercure_account":
        return mercure.privacy_customer_snapshot("account", ref)
    if kind == "mercure_free":
        return mercure.privacy_customer_snapshot("free", ref)
    return None


def export_subject(
    request_id: object,
    db_path: Path | str | None = None,
) -> dict:
    row = _request_row(request_id, db_path)
    locator = _locator(row["request_id"])
    kind, ref = locator["subjectKind"], locator["subjectRef"]
    export = {
        "requestId": row["request_id"],
        "requestType": row["request_type"],
        "generatedAt": _now_iso(),
        "subjectKind": kind,
        "stores": {
            "reminders": _reminder_rows(kind, ref),
            "mobile": _mobile_rows(kind, ref),
            "notifications": _notification_rows(kind, ref),
            "reviewFollowup": _review_rows(kind, ref),
            "booking": _booking_rows(kind, ref),
            "complianceContractEvidence": _compliance_contract_rows(kind, ref, db_path),
        },
    }
    provider_error = ""
    try:
        export["stores"]["mercure"] = _mercure_snapshot(kind, ref)
        if export["stores"]["mercure"] is None and kind != "installation":
            provider_error = "provider_identity_lookup_required"
    except Exception:
        export["stores"]["mercure"] = None
        provider_error = "provider_lookup_unavailable"

    counts = {
        name: (
            len(value)
            if isinstance(value, list)
            else sum(len(v) for v in value.values())
            if isinstance(value, dict)
            else int(value is not None)
        )
        for name, value in export["stores"].items()
    }
    _record_step(
        row["request_id"],
        "checkupauto",
        "export",
        "applied",
        count=sum(counts.values()),
        detail="machine_readable_json",
        evidence={"storeCounts": counts},
        db_path=db_path,
    )
    if provider_error:
        _record_step(
            row["request_id"],
            "mercure",
            "access",
            "manual_required",
            detail=provider_error,
            evidence={"lookupAvailable": False},
            db_path=db_path,
        )
    elif export["stores"].get("mercure") is not None:
        _record_step(
            row["request_id"],
            "mercure",
            "access",
            "applied",
            count=1,
            detail="read_boundary_verified",
            evidence={"lookupAvailable": True},
            db_path=db_path,
        )
    compliance_store.set_rights_request_status(row["request_id"], "in_progress", db_path)
    return export


def _purpose_set(request_type: str, requested: str) -> tuple[str, ...]:
    if request_type == "restriction":
        return ("all_processing",)
    if request_type == "erasure":
        return ("all_processing",)
    if requested == "review_request":
        return ("google_review",)
    if requested == "reminders":
        return ("ct_reminder",)
    if requested == "direct_marketing":
        return suppression.DIRECT_MARKETING_PURPOSES
    return ("all_processing",)


def _linked_identities(kind: str, ref: str) -> list[tuple[str, str]]:
    identities: set[tuple[str, str]] = {(kind, ref)}
    for row in _reminder_rows(kind, ref):
        client_kind = str(row.get("clientKind") or "")
        client_id = str(row.get("clientId") or "")
        vehicle_id = str(row.get("vehicleId") or "")
        if client_id and client_kind in {"account", "free"}:
            identities.add((f"mercure_{client_kind}", client_id))
        if vehicle_id:
            identities.add(("vehicle", vehicle_id))
    for row in _mobile_rows(kind, ref):
        installation = str(row.get("installationId") or "")
        client_kind = str(row.get("clientKind") or "")
        client_id = str(row.get("clientId") or "")
        vehicle_id = str(row.get("vehicleId") or "")
        if installation:
            identities.add(("installation", installation))
        if client_id and client_kind in {"account", "free"}:
            identities.add((f"mercure_{client_kind}", client_id))
        if vehicle_id:
            identities.add(("vehicle", vehicle_id))
    if kind in {"mercure_account", "mercure_free"}:
        try:
            provider = _mercure_snapshot(kind, ref) or {}
            email = str(provider.get("email") or "").strip()
            phone = str(provider.get("telephone") or "").strip()
            if email:
                identities.add(("email", email))
            if phone:
                identities.add(("phone", phone))
        except Exception:
            pass
    return sorted(identities)


def _apply_suppression_network(
    kind: str,
    ref: str,
    purposes: tuple[str, ...],
    request_id: str,
    db_path: Path | str | None,
) -> list[tuple[str, str]]:
    identities = _linked_identities(kind, ref)
    for linked_kind, linked_ref in identities:
        suppression.suppress(
            linked_kind,
            linked_ref,
            purposes,
            source_request_id=request_id,
            db_path=db_path,
        )
    return identities


def execute_request(request_id: object, db_path: Path | str | None = None) -> dict:
    row = _request_row(request_id, db_path)
    locator = _locator(row["request_id"])
    request_type = str(row["request_type"])
    kind, ref = locator["subjectKind"], locator["subjectRef"]
    compliance_store.set_rights_request_status(row["request_id"], "in_progress", db_path)

    if request_type in {"access", "portability"}:
        return {
            "ok": True,
            "requestId": row["request_id"],
            "state": "export_generated",
            "export": export_subject(row["request_id"], db_path),
            "steps": steps(row["request_id"], db_path),
        }

    if request_type in {"objection", "consent_withdrawal", "restriction", "erasure"}:
        purposes = _purpose_set(request_type, locator["purpose"])
        linked = _apply_suppression_network(
            kind,
            ref,
            purposes,
            row["request_id"],
            db_path,
        )
        _record_step(
            row["request_id"],
            "suppression_registry",
            request_type,
            "applied",
            count=len(linked),
            detail="hmac_identity_suppression",
            evidence={
                "purposes": list(purposes),
                "linkedIdentityKinds": sorted({item[0] for item in linked}),
                "linkedIdentityCount": len(linked),
            },
            db_path=db_path,
        )

    if request_type == "erasure":
        reminder_count = _reminder_delete(kind, ref)
        mobile_count = _mobile_delete(kind, ref)
        notification_count = _notification_delete(kind, ref)
        review_count = _review_delete(kind, ref)
        for store, count in (
            ("reminders", reminder_count),
            ("mobile", mobile_count),
            ("notifications", notification_count),
            ("review_followup", review_count),
        ):
            _record_step(
                row["request_id"],
                store,
                "erasure",
                "applied" if count else "not_applicable",
                count=count,
                detail="derived_operational_data",
                evidence={"removedCount": count},
                db_path=db_path,
            )
        retained = _compliance_contract_rows(kind, ref, db_path)
        retained_count = sum(len(value) for value in retained.values())
        if _booking_rows(kind, ref) or retained_count:
            _record_step(
                row["request_id"],
                "contract_evidence",
                "erasure",
                "retained",
                count=len(_booking_rows(kind, ref)) + retained_count,
                detail="legal_or_claims_retention_review",
                evidence={"retainedCount": len(_booking_rows(kind, ref)) + retained_count},
                db_path=db_path,
            )
        if kind != "installation":
            _record_step(
                row["request_id"],
                "mercure",
                "erasure",
                "manual_required",
                detail="provider_mutation_not_verified",
                evidence={"writeApiVerified": False},
                db_path=db_path,
            )

    elif request_type == "restriction":
        count = _reminder_quarantine(kind, ref)
        _record_step(
            row["request_id"],
            "reminders",
            "restriction",
            "applied" if count else "not_applicable",
            count=count,
            detail="quarantined_and_suppressed",
            evidence={"quarantinedCount": count},
            db_path=db_path,
        )
        if kind != "installation":
            _record_step(
                row["request_id"],
                "mercure",
                "restriction",
                "manual_required",
                detail="provider_mutation_not_verified",
                evidence={"writeApiVerified": False},
                db_path=db_path,
            )

    elif request_type in {"objection", "consent_withdrawal"}:
        _record_step(
            row["request_id"],
            "checkupauto_channels",
            request_type,
            "applied",
            count=1,
            detail="suppression_enforced_at_send",
            evidence={"purpose": locator["purpose"]},
            db_path=db_path,
        )

    elif request_type == "rectification":
        _record_step(
            row["request_id"],
            "checkupauto_derived_stores",
            "rectification",
            "retained",
            detail="authoritative_source_is_mercure",
            evidence={"derivedStoresAuthoritative": False},
            db_path=db_path,
        )
        if kind in {"mercure_account", "mercure_free", "contract", "vehicle", "email", "phone"}:
            _record_step(
                row["request_id"],
                "mercure",
                "rectification",
                "manual_required",
                detail="provider_write_api_not_verified",
                evidence={
                    "writeApiVerified": False,
                    "requestedFieldCount": len(locator["rectification"]),
                },
                db_path=db_path,
            )
        else:
            _record_step(
                row["request_id"],
                "mobile",
                "rectification",
                "not_applicable",
                detail="no_mutable_identity_field",
                evidence={},
                db_path=db_path,
            )
    else:
        raise ValueError("type de droit non pris en charge")

    current_steps = steps(row["request_id"], db_path)
    blockers = [item for item in current_steps if item["status"] in MANUAL_STATES]
    if not blockers and request_type in {"objection", "consent_withdrawal"}:
        compliance_store.set_rights_request_status(row["request_id"], "closed", db_path)
        _clear_locator(row["request_id"])
        state = "closed"
    else:
        state = "in_progress"
    return {
        "ok": not any(item["status"] == "failed" for item in current_steps),
        "requestId": row["request_id"],
        "state": state,
        "blockerCount": len(blockers),
        "steps": current_steps,
    }


def complete_manual_step(
    request_id: object,
    store: object,
    action: object,
    *,
    evidence_code: object,
    db_path: Path | str | None = None,
) -> dict:
    row = _request_row(request_id, db_path)
    safe_store = str(store or "").strip()
    safe_action = str(action or "").strip()
    code = str(evidence_code or "").strip()
    if not code or len(code) > 120:
        raise ValueError("evidenceCode requis")
    existing = next(
        (
            item for item in steps(row["request_id"], db_path)
            if item["store"] == safe_store and item["action"] == safe_action
        ),
        None,
    )
    if not existing or existing["status"] != "manual_required":
        raise ValueError("étape manuelle introuvable")
    _record_step(
        row["request_id"],
        safe_store,
        safe_action,
        "applied",
        count=existing["affectedCount"],
        detail="manual_action_evidenced",
        evidence={"evidenceCodeHash": hashlib.sha256(code.encode("utf-8")).hexdigest()},
        db_path=db_path,
    )
    return {"ok": True, "requestId": row["request_id"], "steps": steps(row["request_id"], db_path)}


def reject_request(
    request_id: object,
    *,
    reason_code: object,
    db_path: Path | str | None = None,
) -> dict:
    row = _request_row(request_id, db_path)
    code = str(reason_code or "").strip()
    if not code or len(code) > 120:
        raise ValueError("reasonCode requis")
    result = compliance_store.set_rights_request_status(row["request_id"], "rejected", db_path)
    _clear_locator(row["request_id"])
    compliance_operations.record_audit_evidence(
        "rights_request",
        row["request_id"],
        "reject",
        {"reasonCodeHash": hashlib.sha256(code.encode("utf-8")).hexdigest()},
        db_path,
    )
    return {**result, "locatorCleared": True}


def complete_request(request_id: object, db_path: Path | str | None = None) -> dict:
    row = _request_row(request_id, db_path)
    current = steps(row["request_id"], db_path)
    if not current:
        raise RuntimeError("demande non exécutée")
    blockers = [item for item in current if item["status"] in MANUAL_STATES]
    if blockers:
        raise RuntimeError("étapes requises non terminées")
    result = compliance_store.set_rights_request_status(row["request_id"], "closed", db_path)
    _clear_locator(row["request_id"])
    compliance_operations.record_audit_evidence(
        "rights_request",
        row["request_id"],
        "close",
        {"stepEvidenceHashes": [item["evidenceHash"] for item in current]},
        db_path,
    )
    return {**result, "locatorCleared": True}


def request_details(request_id: object, db_path: Path | str | None = None) -> dict:
    row = _request_row(request_id, db_path)
    try:
        locator = _locator(row["request_id"])
        subject_kind = locator["subjectKind"]
        purpose = locator["purpose"]
        available = True
    except RuntimeError:
        subject_kind = ""
        purpose = ""
        available = False
    return {
        "id": row["request_id"],
        "type": row["request_type"],
        "status": row["status"],
        "subjectKind": subject_kind,
        "purpose": purpose,
        "locatorAvailable": available,
        "receivedAt": row["received_at"],
        "dueAt": row["due_at"],
        "closedAt": row["closed_at"],
        "steps": steps(row["request_id"], db_path),
    }


def snapshot(db_path: Path | str | None = None) -> dict:
    init_db(db_path)
    rows = compliance_store.rights_requests(db_path, 500)
    details = {}
    for row in rows:
        try:
            details[row["id"]] = request_details(row["id"], db_path)
        except Exception:
            details[row["id"]] = {
                "id": row["id"],
                "type": row["type"],
                "status": row["status"],
                "subjectKind": "",
                "purpose": "",
                "locatorAvailable": False,
                "steps": [],
            }
    capability_state = capability()
    unresolved = sum(
        1
        for row in rows
        if row["status"] not in {"closed", "rejected"}
        and not bool((details.get(row["id"]) or {}).get("locatorAvailable"))
    )
    capability_state["unresolvedLocatorCount"] = unresolved
    capability_state["operationalReady"] = unresolved == 0
    return {
        "capability": capability_state,
        "suppression": suppression.summary(db_path),
        "requests": details,
    }


def capability() -> dict:
    return {
        "bound": True,
        "requestTypes": sorted(compliance_store.RIGHT_TYPES),
        "localExecution": True,
        "machineReadableExport": True,
        "suppressionEnforcedAtSend": True,
        "antiResurrectionGuard": True,
        "mercureReadBoundary": True,
        "mercureMutationMode": "manual_evidenced_until_verified_api_exists",
        "locatorLifecycle": "private_vault_deleted_on_close",
        "auditEvidence": "SHA-256",
    }
