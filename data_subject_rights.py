from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import re
import sqlite3
import uuid
from pathlib import Path

import compliance_contract_rights
import compliance_store
import mercure_rights
import mobile_devices
import privacy_suppression
import rights_subject_bindings


SUPPORTED_ADAPTERS = {
    "mobile_installation": ("access", "portability", "erasure"),
    "mercure_customer_contact": ("access", "portability"),
    "compliance_contracts": ("access", "portability"),
    "privacy_suppression": ("restriction", "objection", "consent_withdrawal", "erasure"),
}
# Bounded or dependency-limited work remains useful evidence, but may need to be
# repeated after a provider/local dependency outage. Retries stop permanently
# once the adapter-specific completion action exists.
RETRYABLE_PARTIAL_ADAPTERS = {
    "mercure_customer_contact": "export_complete",
    "privacy_suppression": "suppress_complete",
}


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _request_id(value: object) -> str:
    raw = str(value or "").strip().lower()
    if len(raw) != 32:
        raise ValueError("requestId invalide")
    try:
        int(raw, 16)
    except ValueError as exc:
        raise ValueError("requestId invalide") from exc
    return raw


def _mobile_installation(value: object) -> str:
    raw = str(value or "").strip().lower()
    try:
        parsed = uuid.UUID(raw)
    except (ValueError, AttributeError) as exc:
        raise ValueError("subjectRef mobile invalide") from exc
    if str(parsed) != raw:
        raise ValueError("subjectRef mobile invalide")
    return raw


def _init_audit(db_path: Path | str | None = None) -> None:
    compliance_store.init_db(db_path)
    with compliance_store.connect(db_path) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS rights_execution_audit(
              execution_id TEXT PRIMARY KEY,
              request_id TEXT NOT NULL,
              request_type TEXT NOT NULL,
              adapter TEXT NOT NULL,
              action TEXT NOT NULL,
              evidence_hash TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_rights_execution_request
              ON rights_execution_audit(request_id,created_at);
            """
        )


def _request(request_id: str, db_path: Path | str | None = None) -> sqlite3.Row:
    compliance_store.init_db(db_path)
    with compliance_store.connect(db_path) as db:
        row = db.execute(
            """SELECT request_id,request_type,status,subject_ref_hash,received_at,due_at,closed_at
               FROM rights_requests WHERE request_id=?""",
            (request_id,),
        ).fetchone()
    if not row:
        raise LookupError("demande inconnue")
    return row


def _verify_subject(
    row: sqlite3.Row,
    subject_ref: str,
    adapter: str,
    db_path: Path | str | None = None,
) -> None:
    digest = hashlib.sha256(subject_ref.encode("utf-8")).hexdigest()
    if hmac.compare_digest(str(row["subject_ref_hash"]), digest):
        return
    if rights_subject_bindings.is_bound(
        str(row["request_id"]),
        adapter,
        subject_ref,
        db_path,
    ):
        return
    if adapter == "privacy_suppression" and rights_subject_bindings.is_bound(
        str(row["request_id"]),
        "mercure_customer_contact",
        subject_ref,
        db_path,
    ):
        return
    raise PermissionError("référence du demandeur refusée")


def _adapter_actions(
    request_id: str,
    adapter: str,
    db_path: Path | str | None = None,
) -> list[str]:
    _init_audit(db_path)
    with compliance_store.connect(db_path) as db:
        rows = db.execute(
            """SELECT action FROM rights_execution_audit
               WHERE request_id=? AND adapter=? ORDER BY created_at,execution_id""",
            (request_id, adapter),
        ).fetchall()
    return [str(row["action"]) for row in rows]


def _adapter_executed(request_id: str, adapter: str, db_path: Path | str | None = None) -> bool:
    return bool(_adapter_actions(request_id, adapter, db_path))


def _adapter_can_retry_partial(
    request_id: str,
    adapter: str,
    db_path: Path | str | None = None,
) -> bool:
    actions = _adapter_actions(request_id, adapter, db_path)
    if not actions:
        return True
    completion_action = RETRYABLE_PARTIAL_ADAPTERS.get(adapter, "")
    return bool(completion_action and completion_action not in actions)


def _completed_privacy_suppression_erasure_result(
    row: sqlite3.Row,
    db_path: Path | str | None = None,
) -> dict:
    """Return a replay context without writing a second suppression audit."""
    _init_audit(db_path)
    with compliance_store.connect(db_path) as db:
        execution = db.execute(
            """SELECT execution_id FROM rights_execution_audit
               WHERE request_id=? AND adapter='privacy_suppression'
                 AND action='suppress_complete'
               ORDER BY created_at DESC,execution_id DESC LIMIT 1""",
            (row["request_id"],),
        ).fetchone()
    if not execution:
        raise RuntimeError("audit de suppression complète introuvable")
    return {
        "ok": True,
        "requestId": str(row["request_id"]),
        "requestType": "erasure",
        "adapter": "privacy_suppression",
        "purposes": ["all_processing"],
        "identityResolutionComplete": True,
        "recoveredFromCompletedAudit": True,
        "executionId": str(execution["execution_id"]),
        "requestStatus": str(row["status"]),
        "requestComplete": False,
    }


def _mobile_snapshot(installation_id: str) -> dict:
    mobile_devices.init_db()
    with mobile_devices.connect() as db:
        device = db.execute(
            """SELECT installation_id,environment,created_at,updated_at,last_seen_at,
                      disabled_at,disabled_reason,device_token
               FROM mobile_device WHERE installation_id=?""",
            (installation_id,),
        ).fetchone()
        deadlines = db.execute(
            """SELECT deadline_id,due_date,source,created_at,updated_at
               FROM mobile_deadline WHERE installation_id=?
               ORDER BY due_date,deadline_id""",
            (installation_id,),
        ).fetchall()
        bindings = db.execute(
            """SELECT binding_id,vehicle_id,client_kind,client_id,created_at,updated_at
               FROM mobile_vehicle_binding WHERE installation_id=?
               ORDER BY created_at,binding_id""",
            (installation_id,),
        ).fetchall()
    return {
        "installationId": installation_id,
        "device": (
            {
                "installationId": str(device["installation_id"]),
                "environment": str(device["environment"]),
                "createdAt": str(device["created_at"]),
                "updatedAt": str(device["updated_at"]),
                "lastSeenAt": str(device["last_seen_at"]),
                "disabledAt": str(device["disabled_at"]),
                "disabledReason": str(device["disabled_reason"]),
                "pushTokenPresent": bool(device["device_token"]),
            }
            if device
            else None
        ),
        "deadlines": [
            {
                "deadlineId": str(row["deadline_id"]),
                "dueDate": str(row["due_date"]),
                "source": str(row["source"]),
                "createdAt": str(row["created_at"]),
                "updatedAt": str(row["updated_at"]),
            }
            for row in deadlines
        ],
        "vehicleBindings": [
            {
                "bindingId": str(row["binding_id"]),
                "vehicleId": str(row["vehicle_id"]),
                "clientKind": str(row["client_kind"]),
                "clientId": str(row["client_id"]),
                "createdAt": str(row["created_at"]),
                "updatedAt": str(row["updated_at"]),
            }
            for row in bindings
        ],
    }


def _audit_execution(
    row: sqlite3.Row,
    adapter: str,
    action: str,
    evidence: dict,
    db_path: Path | str | None = None,
) -> str:
    """Record one store-level execution without closing the global rights request.

    A rights request spans every applicable personal-data store. Until the engine
    can prove complete cross-store coverage, a successful adapter execution only
    moves the request to ``in_progress``. A retryable adapter may append partial
    evidence until its completion action is reached; completed and non-retryable
    adapters remain single-execution and fail closed under races.
    """
    _init_audit(db_path)
    canonical = json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    evidence_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    execution_id = uuid.uuid4().hex
    stamp = _now_iso()
    with compliance_store.connect(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        current = db.execute(
            "SELECT status FROM rights_requests WHERE request_id=?",
            (row["request_id"],),
        ).fetchone()
        if not current or str(current["status"]) not in {"open", "in_progress"}:
            raise RuntimeError("demande non exécutable")
        previous = db.execute(
            """SELECT action FROM rights_execution_audit
               WHERE request_id=? AND adapter=?""",
            (row["request_id"], adapter),
        ).fetchall()
        if previous:
            completion_action = RETRYABLE_PARTIAL_ADAPTERS.get(adapter, "")
            previous_actions = {str(item["action"]) for item in previous}
            if not completion_action or completion_action in previous_actions:
                raise RuntimeError("adaptateur déjà exécuté pour cette demande")
        db.execute(
            """INSERT INTO rights_execution_audit(
                 execution_id,request_id,request_type,adapter,action,evidence_hash,created_at
               ) VALUES(?,?,?,?,?,?,?)""",
            (
                execution_id,
                row["request_id"],
                row["request_type"],
                adapter,
                action,
                evidence_hash,
                stamp,
            ),
        )
        db.execute(
            "UPDATE rights_requests SET status='in_progress',closed_at='' WHERE request_id=?",
            (row["request_id"],),
        )
    return execution_id


def _suppression_subject(subject_ref: str) -> tuple[str, str]:
    raw = str(subject_ref or "").strip()
    try:
        return "installation", _mobile_installation(raw)
    except ValueError:
        pass
    try:
        client_kind, client_id = mercure_rights.parse_subject_ref(raw)
        return f"mercure_{client_kind}", client_id
    except ValueError:
        pass
    if re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", raw):
        return "email", raw.lower()
    phone = re.sub(r"[^+0-9]", "", raw)
    if re.fullmatch(r"\+?[0-9]{6,20}", phone):
        return "phone", phone
    raise ValueError("subjectRef suppression invalide")


def _suppression_purposes(request_type: str, purpose: str) -> tuple[str, ...]:
    requested = str(purpose or "").strip()
    if request_type in {"restriction", "erasure"}:
        return ("all_processing",)
    if requested == "direct_marketing":
        return privacy_suppression.DIRECT_MARKETING_PURPOSES
    if requested in {"google_review", "direct_marketing_email", "direct_marketing_phone",
                     "direct_marketing_sms", "direct_marketing_push"}:
        if request_type == "consent_withdrawal" and requested == "google_review":
            raise ValueError("retrait du consentement non applicable à cette finalité")
        return (requested,)
    if request_type in {"objection", "consent_withdrawal"}:
        return privacy_suppression.DIRECT_MARKETING_PURPOSES
    raise ValueError("finalité de suppression invalide")


def _linked_suppression_identities(
    subject_kind: str,
    subject_value: str,
) -> tuple[list[tuple[str, str]], dict]:
    """Resolve identities linked to one suppression subject without hiding gaps.

    A provider or local binding failure must not undo suppression already applied
    to identities we can prove. It does, however, make this resolution attempt
    partial so the same rights adapter remains retryable until every required
    linkage source was successfully inspected.
    """
    identities: set[tuple[str, str]] = {(subject_kind, subject_value)}
    mercure_refs: list[str] = []
    mobile_bindings_required = subject_kind == "installation"
    mobile_bindings_resolved = not mobile_bindings_required

    if mobile_bindings_required:
        try:
            bindings = mobile_devices.registered_vehicle_bindings(subject_value)
            mobile_bindings_resolved = True
            for row in bindings:
                client_kind = str(row.get("client_kind") or "")
                client_id = str(row.get("client_id") or "")
                vehicle_id = str(row.get("vehicle_id") or "")
                if client_kind in {"account", "free"} and client_id:
                    identities.add((f"mercure_{client_kind}", client_id))
                    mercure_refs.append(f"{client_kind}:{client_id}")
                if vehicle_id:
                    identities.add(("vehicle", vehicle_id))
        except Exception:
            mobile_bindings_resolved = False
    elif subject_kind in {"mercure_account", "mercure_free"}:
        kind = "account" if subject_kind == "mercure_account" else "free"
        mercure_refs.append(f"{kind}:{subject_value}")

    unique_mercure_refs = list(dict.fromkeys(mercure_refs))
    provider_resolved_count = 0
    for mercure_ref in unique_mercure_refs:
        try:
            snapshot = mercure_rights.contact_snapshot(mercure_ref)
            contact = snapshot.get("contact") or {}
            email = str(contact.get("email") or "").strip()
            phone = str(contact.get("telephone") or "").strip()
            if email:
                identities.add(("email", email.lower()))
            if phone:
                identities.add(("phone", phone))
            provider_resolved_count += 1
        except Exception:
            continue

    provider_contact_required = bool(unique_mercure_refs)
    provider_contact_resolved = provider_resolved_count == len(unique_mercure_refs)
    resolution_complete = mobile_bindings_resolved and provider_contact_resolved
    resolution = {
        "mobileBindingsRequired": mobile_bindings_required,
        "mobileBindingsResolved": mobile_bindings_resolved,
        "providerContactRequired": provider_contact_required,
        "providerContactResolved": provider_contact_resolved,
        "providerContactCount": len(unique_mercure_refs),
        "providerContactResolvedCount": provider_resolved_count,
        "resolutionComplete": resolution_complete,
    }
    return sorted(identities), resolution


def _execute_privacy_suppression(
    row: sqlite3.Row,
    subject_ref: str,
    purpose: str,
    db_path: Path | str | None = None,
) -> tuple[dict, dict]:
    request_type = str(row["request_type"])
    subject_kind, subject_value = _suppression_subject(subject_ref)
    purposes = _suppression_purposes(request_type, purpose)
    identities, resolution = _linked_suppression_identities(subject_kind, subject_value)
    for kind, value in identities:
        privacy_suppression.suppress(
            kind,
            value,
            purposes,
            request_id=str(row["request_id"]),
            db_path=db_path,
        )
    result = {
        "ok": True,
        "requestId": str(row["request_id"]),
        "requestType": request_type,
        "adapter": "privacy_suppression",
        "purposes": list(purposes),
        "suppressedIdentityCount": len(identities),
        "identityResolutionComplete": bool(resolution["resolutionComplete"]),
        "mobileBindingsRequired": bool(resolution["mobileBindingsRequired"]),
        "mobileBindingsResolved": bool(resolution["mobileBindingsResolved"]),
        "providerContactRequired": bool(resolution["providerContactRequired"]),
        "providerContactResolved": bool(resolution["providerContactResolved"]),
    }
    evidence = {
        "requestId": str(row["request_id"]),
        "requestType": request_type,
        "adapter": "privacy_suppression",
        "purposes": list(purposes),
        "identityKinds": sorted({kind for kind, _ in identities}),
        "suppressedIdentityCount": len(identities),
        "identityResolutionComplete": bool(resolution["resolutionComplete"]),
        "mobileBindingsRequired": bool(resolution["mobileBindingsRequired"]),
        "mobileBindingsResolved": bool(resolution["mobileBindingsResolved"]),
        "providerContactRequired": bool(resolution["providerContactRequired"]),
        "providerContactResolved": bool(resolution["providerContactResolved"]),
        "providerContactCount": int(resolution["providerContactCount"]),
        "providerContactResolvedCount": int(resolution["providerContactResolvedCount"]),
    }
    return result, evidence


def bind_mercure_from_mobile(
    request_id: object,
    installation_id: object,
    mercure_subject_ref: object,
    db_path: Path | str | None = None,
) -> dict:
    rid = _request_id(request_id)
    return rights_subject_bindings.bind_mercure_from_mobile(
        rid,
        installation_id,
        mercure_subject_ref,
        db_path,
    )


def execute(
    request_id: object,
    subject_ref: object,
    *,
    adapter: str,
    purpose: str = "",
    db_path: Path | str | None = None,
    resume_completed_erasure: bool = False,
) -> dict:
    rid = _request_id(request_id)
    adapter = str(adapter or "").strip()
    if adapter not in SUPPORTED_ADAPTERS:
        raise ValueError("adaptateur de droit non pris en charge")
    row = _request(rid, db_path)
    if str(row["status"]) not in {"open", "in_progress"}:
        raise RuntimeError("demande non exécutable")
    ref = str(subject_ref or "").strip()
    _verify_subject(row, ref, adapter, db_path)
    request_type = str(row["request_type"])
    if request_type not in SUPPORTED_ADAPTERS[adapter]:
        raise NotImplementedError("type de droit non pris en charge par cet adaptateur")
    if not _adapter_can_retry_partial(rid, adapter, db_path):
        if (
            resume_completed_erasure is True
            and adapter == "privacy_suppression"
            and request_type == "erasure"
        ):
            return _completed_privacy_suppression_erasure_result(row, db_path)
        raise RuntimeError("adaptateur déjà exécuté pour cette demande")

    if adapter == "mobile_installation":
        installation_id = _mobile_installation(ref)
        if request_type in {"access", "portability"}:
            data = _mobile_snapshot(installation_id)
            action = "export"
            result = {
                "ok": True,
                "requestId": rid,
                "requestType": request_type,
                "adapter": adapter,
                "format": "application/json",
                "data": data,
            }
            evidence = {
                "requestId": rid,
                "requestType": request_type,
                "adapter": adapter,
                "devicePresent": data["device"] is not None,
                "deadlineCount": len(data["deadlines"]),
                "vehicleBindingCount": len(data["vehicleBindings"]),
                "exportHash": hashlib.sha256(
                    json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                ).hexdigest(),
            }
        else:
            # Keep one erasure implementation. The dedicated boundary persists the
            # receipt atomically with mobile deletion, then records the compliance
            # audit separately so an interrupted audit can be recovered safely.
            # Lazy import avoids the module cycle: mobile_dsar_erasure intentionally
            # reuses the validation and audit primitives defined in this module.
            import mobile_dsar_erasure

            return mobile_dsar_erasure.execute(rid, installation_id, db_path)
    elif adapter == "mercure_customer_contact":
        data = mercure_rights.contact_snapshot(ref)
        export_complete = not bool(data.get("partial", True))
        action = "export_complete" if export_complete else "export"
        result = {
            "ok": True,
            "requestId": rid,
            "requestType": request_type,
            "adapter": adapter,
            "format": "application/json",
            "data": data,
        }
        evidence = {
            "requestId": rid,
            "requestType": request_type,
            "adapter": adapter,
            "partial": not export_complete,
            "coverageComplete": export_complete,
            "emailPresent": bool(data["contact"]["email"]),
            "telephonePresent": bool(data["contact"]["telephone"]),
            "exportHash": hashlib.sha256(
                json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
        }
    elif adapter == "compliance_contracts":
        data = compliance_contract_rights.snapshot(ref, db_path)
        action = "export"
        result = {
            "ok": True,
            "requestId": rid,
            "requestType": request_type,
            "adapter": adapter,
            "format": "application/json",
            "data": data,
        }
        evidence = {
            "requestId": rid,
            "requestType": request_type,
            "adapter": adapter,
            "partial": True,
            "consentReceiptCount": len(data["consentReceipts"]),
            "checkoutAcceptanceCount": len(data["checkoutAcceptances"]),
            "exportHash": hashlib.sha256(
                json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
        }
    elif adapter == "privacy_suppression":
        result, evidence = _execute_privacy_suppression(row, ref, purpose, db_path)
        action = (
            "suppress_complete"
            if result["identityResolutionComplete"]
            else "suppress_partial"
        )
    else:  # pragma: no cover - guarded by SUPPORTED_ADAPTERS
        raise ValueError("adaptateur de droit non pris en charge")

    execution_id = _audit_execution(row, adapter, action, evidence, db_path)
    result["executionId"] = execution_id
    result["requestStatus"] = "in_progress"
    result["requestComplete"] = False
    return result


def audit_rows(db_path: Path | str | None = None, limit: int = 100) -> list[dict]:
    _init_audit(db_path)
    with compliance_store.connect(db_path) as db:
        rows = db.execute(
            """SELECT execution_id,request_id,request_type,adapter,action,evidence_hash,created_at
               FROM rights_execution_audit ORDER BY created_at DESC LIMIT ?""",
            (max(1, min(int(limit), 500)),),
        ).fetchall()
    return [
        {
            "executionId": str(row["execution_id"]),
            "requestId": str(row["request_id"]),
            "requestType": str(row["request_type"]),
            "adapter": str(row["adapter"]),
            "action": str(row["action"]),
            "evidenceHash": str(row["evidence_hash"]),
            "createdAt": str(row["created_at"]),
        }
        for row in rows
    ]


def capability(db_path: Path | str | None = None) -> dict:
    _init_audit(db_path)
    with compliance_store.connect(db_path) as db:
        execution_count = int(db.execute("SELECT COUNT(*) n FROM rights_execution_audit").fetchone()["n"])
    return {
        "bound": False,
        "partial": True,
        "supportedAdapters": {
            name: list(rights) for name, rights in sorted(SUPPORTED_ADAPTERS.items())
        },
        "rawSubjectReferencePersisted": False,
        "subjectReferenceReverifiedAtExecution": True,
        "crossStoreSubjectBindings": True,
        "subjectBindingProvenance": ["mobile_vehicle_binding"],
        "partialExecutionClosesRequest": False,
        "auditStoresEvidenceHashOnly": True,
        "retryablePartialAdapters": dict(sorted(RETRYABLE_PARTIAL_ADAPTERS.items())),
        "executionCount": execution_count,
        "remainingRightTypes": [
            "rectification",
        ],
        "partialSystemAdapters": ["mercure", "compliance_contracts"],
        "remainingSystemAdapters": [
            "mercure",
            "referral_wallet",
            "compliance_contracts",
            "retention_purge",
        ],
    }
