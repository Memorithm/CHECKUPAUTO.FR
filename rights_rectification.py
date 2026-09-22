from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import uuid
from pathlib import Path

import data_subject_rights as rights
import mobile_devices


ADAPTER = "mobile_deadline_rectification"
FIELD = "device_deadline_due_date"


def _deadline_id(value: object) -> str:
    raw = str(value or "").strip().lower()
    try:
        parsed = uuid.UUID(raw)
    except (ValueError, AttributeError) as exc:
        raise ValueError("deadlineId invalide") from exc
    if str(parsed) != raw:
        raise ValueError("deadlineId invalide")
    return raw


def _due_date(value: object) -> str:
    raw = str(value or "").strip()
    try:
        parsed = datetime.date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError("dueDate invalide") from exc
    if parsed.year < 2020 or parsed.year > 2100:
        raise ValueError("dueDate invalide")
    return parsed.isoformat()


def _correction(value: object) -> tuple[str, str]:
    if not isinstance(value, dict) or set(value) != {"deadlineId", "dueDate"}:
        raise ValueError("correction invalide")
    return _deadline_id(value["deadlineId"]), _due_date(value["dueDate"])


def _verify_primary_subject(row, installation_id: str) -> None:
    digest = hashlib.sha256(installation_id.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(str(row["subject_ref_hash"]), digest):
        raise PermissionError("référence du demandeur refusée")


def execute(
    request_id: object,
    subject_ref: object,
    correction: object,
    db_path: Path | str | None = None,
) -> dict:
    """Rectify one user-managed mobile deadline without touching Mercure truth.

    The operation is deliberately narrow: only an existing ``source=device`` due
    date can be changed. Authoritative Mercure deadlines, vehicle bindings and
    device credentials are outside this executor and therefore fail closed.
    """
    rid = rights._request_id(request_id)
    row = rights._request(rid, db_path)
    if str(row["status"]) not in {"open", "in_progress"}:
        raise RuntimeError("demande non exécutable")
    if str(row["request_type"]) != "rectification":
        raise NotImplementedError("type de droit non pris en charge par cet adaptateur")

    installation_id = rights._mobile_installation(subject_ref)
    _verify_primary_subject(row, installation_id)
    if rights._adapter_executed(rid, ADAPTER, db_path):
        raise RuntimeError("adaptateur déjà exécuté pour cette demande")
    deadline_id, due_date = _correction(correction)

    mobile_devices.init_db()
    now = rights._now_iso()
    with mobile_devices.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        device = db.execute(
            "SELECT installation_id FROM mobile_device WHERE installation_id=?",
            (installation_id,),
        ).fetchone()
        if not device:
            raise LookupError("installation mobile introuvable")
        deadline = db.execute(
            """SELECT source FROM mobile_deadline
               WHERE installation_id=? AND deadline_id=?""",
            (installation_id, deadline_id),
        ).fetchone()
        if not deadline:
            raise LookupError("échéance mobile introuvable")
        if str(deadline["source"]) != mobile_devices.DEVICE_DEADLINE_SOURCE:
            raise PermissionError("échéance autoritaire non rectifiable")
        db.execute(
            """UPDATE mobile_deadline SET due_date=?,updated_at=?
               WHERE installation_id=? AND deadline_id=? AND source=?""",
            (
                due_date,
                now,
                installation_id,
                deadline_id,
                mobile_devices.DEVICE_DEADLINE_SOURCE,
            ),
        )

    correction_hash = hashlib.sha256(
        json.dumps(
            {"deadlineId": deadline_id, "dueDate": due_date},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    evidence = {
        "requestId": rid,
        "requestType": "rectification",
        "adapter": ADAPTER,
        "field": FIELD,
        "source": mobile_devices.DEVICE_DEADLINE_SOURCE,
        "recordCount": 1,
        "correctionHash": correction_hash,
    }
    execution_id = rights._audit_execution(row, ADAPTER, "rectify", evidence, db_path)
    return {
        "ok": True,
        "requestId": rid,
        "requestType": "rectification",
        "adapter": ADAPTER,
        "field": FIELD,
        "source": mobile_devices.DEVICE_DEADLINE_SOURCE,
        "updated": True,
        "executionId": execution_id,
        "requestStatus": "in_progress",
        "requestComplete": False,
    }


def capability() -> dict:
    return {
        "bound": False,
        "partial": True,
        "adapter": ADAPTER,
        "requestType": "rectification",
        "supportedFields": [FIELD],
        "mutableSources": [mobile_devices.DEVICE_DEADLINE_SOURCE],
        "authoritativeSourcesMutable": False,
        "primarySubjectRequired": True,
        "rawSubjectReferencePersisted": False,
        "auditStoresEvidenceHashOnly": True,
    }
