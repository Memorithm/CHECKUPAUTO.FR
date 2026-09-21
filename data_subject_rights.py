from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import sqlite3
import uuid
from pathlib import Path

import compliance_store
import mercure_rights
import mobile_devices
import rights_subject_bindings


SUPPORTED_ADAPTERS = {
    "mobile_installation": ("access", "portability", "erasure"),
    "mercure_customer_contact": ("access", "portability"),
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
    raise PermissionError("référence du demandeur refusée")


def _adapter_executed(request_id: str, adapter: str, db_path: Path | str | None = None) -> bool:
    _init_audit(db_path)
    with compliance_store.connect(db_path) as db:
        row = db.execute(
            "SELECT 1 FROM rights_execution_audit WHERE request_id=? AND adapter=? LIMIT 1",
            (request_id, adapter),
        ).fetchone()
    return row is not None


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


def _erase_mobile(installation_id: str) -> dict:
    mobile_devices.init_db()
    with mobile_devices.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        device_count = int(
            db.execute(
                "SELECT COUNT(*) n FROM mobile_device WHERE installation_id=?",
                (installation_id,),
            ).fetchone()["n"]
        )
        deadline_count = int(
            db.execute(
                "SELECT COUNT(*) n FROM mobile_deadline WHERE installation_id=?",
                (installation_id,),
            ).fetchone()["n"]
        )
        binding_count = int(
            db.execute(
                "SELECT COUNT(*) n FROM mobile_vehicle_binding WHERE installation_id=?",
                (installation_id,),
            ).fetchone()["n"]
        )
        db.execute("DELETE FROM mobile_deadline WHERE installation_id=?", (installation_id,))
        db.execute("DELETE FROM mobile_vehicle_binding WHERE installation_id=?", (installation_id,))
        db.execute("DELETE FROM mobile_device WHERE installation_id=?", (installation_id,))
    return {
        "installationId": installation_id,
        "removed": {
            "deviceRecords": device_count,
            "deadlineRecords": deadline_count,
            "vehicleBindingRecords": binding_count,
        },
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
    moves the request to ``in_progress``. Closing it here would incorrectly claim
    completion while other stores remain untouched.
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
        duplicate = db.execute(
            "SELECT 1 FROM rights_execution_audit WHERE request_id=? AND adapter=? LIMIT 1",
            (row["request_id"], adapter),
        ).fetchone()
        if duplicate:
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
    db_path: Path | str | None = None,
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
    if _adapter_executed(rid, adapter, db_path):
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
            data = _erase_mobile(installation_id)
            action = "erase"
            result = {
                "ok": True,
                "requestId": rid,
                "requestType": request_type,
                "adapter": adapter,
                "removed": data["removed"],
            }
            evidence = {
                "requestId": rid,
                "requestType": request_type,
                "adapter": adapter,
                "removed": data["removed"],
            }
    elif adapter == "mercure_customer_contact":
        data = mercure_rights.contact_snapshot(ref)
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
            "emailPresent": bool(data["contact"]["email"]),
            "telephonePresent": bool(data["contact"]["telephone"]),
            "exportHash": hashlib.sha256(
                json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
        }
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
        "executionCount": execution_count,
        "remainingRightTypes": [
            "rectification",
            "restriction",
            "objection",
            "consent_withdrawal",
        ],
        "partialSystemAdapters": ["mercure"],
        "remainingSystemAdapters": [
            "mercure",
            "notification_broker",
            "referral_wallet",
            "compliance_contracts",
        ],
    }
