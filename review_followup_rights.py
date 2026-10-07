from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

import data_subject_rights
import mercure_rights
import review_followup
import review_followup_privacy
import rights_subject_bindings


ADAPTER = "review_followup"
SUPPORTED_RIGHTS = ("access", "portability", "erasure")
_CHUNK_SIZE = 400


def _verify_mercure_subject(
    row,
    subject_ref: str,
    db_path: Path | str | None = None,
) -> str:
    client_kind, client_id = mercure_rights.parse_subject_ref(subject_ref)
    canonical = f"{client_kind}:{client_id}"
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if hmac.compare_digest(str(row["subject_ref_hash"]), digest):
        return canonical
    if rights_subject_bindings.is_bound(
        str(row["request_id"]),
        rights_subject_bindings.MERCURE_CONTACT_ADAPTER,
        canonical,
        db_path,
    ):
        return canonical
    raise PermissionError("référence Mercure du demandeur refusée")


def _appointment_inventory(subject_ref: str) -> tuple[str, ...]:
    try:
        snapshot = mercure_rights.contact_snapshot(subject_ref)
    except Exception as exc:
        raise RuntimeError("inventaire Mercure des rendez-vous indisponible") from exc

    coverage = snapshot.get("coverage") or {}
    inventory = snapshot.get("operationalInventory") or {}
    rows = inventory.get("appointments") or []
    if (
        coverage.get("appointments") is not True
        or inventory.get("state") != "available"
        or inventory.get("appointmentsTruncated")
        or int(inventory.get("appointmentIdsMissing") or 0) != 0
        or not isinstance(rows, list)
    ):
        raise RuntimeError("inventaire Mercure des rendez-vous incomplet")

    appointment_ids: list[str] = []
    seen: set[str] = set()
    for item in rows:
        if not isinstance(item, dict):
            raise RuntimeError("inventaire Mercure des rendez-vous invalide")
        appointment_id = str(item.get("appointmentId") or "").strip()
        if not appointment_id or len(appointment_id) > 128:
            raise RuntimeError("preuve Mercure de rendez-vous incomplète")
        if appointment_id not in seen:
            seen.add(appointment_id)
            appointment_ids.append(appointment_id)
        if len(appointment_ids) > review_followup_privacy.MAX_APPOINTMENT_IDS:
            raise RuntimeError("inventaire Mercure des rendez-vous trop volumineux")

    try:
        provider_count = int(inventory.get("appointmentCountInWindow"))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("inventaire Mercure des rendez-vous incohérent") from exc
    if provider_count != len(appointment_ids):
        raise RuntimeError("inventaire Mercure des rendez-vous incohérent")
    return tuple(sorted(appointment_ids))


def snapshot_appointments(appointment_ids: tuple[str, ...]) -> dict:
    review_followup.init_db()
    records: list[dict] = []
    with review_followup.connect() as db:
        for start in range(0, len(appointment_ids), _CHUNK_SIZE):
            chunk = appointment_ids[start : start + _CHUNK_SIZE]
            placeholders = ",".join("?" for _ in chunk)
            rows = db.execute(
                f"""SELECT appointment_id,first_seen_at,last_attempt_at,sent_at,
                           status,attempts,last_error
                    FROM review_followup
                    WHERE appointment_id IN ({placeholders})
                    ORDER BY appointment_id""",
                chunk,
            ).fetchall()
            records.extend(
                {
                    "appointmentId": str(row["appointment_id"]),
                    "firstSeenAt": str(row["first_seen_at"]),
                    "lastAttemptAt": str(row["last_attempt_at"]),
                    "sentAt": str(row["sent_at"]),
                    "status": str(row["status"]),
                    "attempts": int(row["attempts"] or 0),
                    "lastError": str(row["last_error"]),
                }
                for row in rows
            )
    return {
        "records": records,
        "recordCount": len(records),
        "appointmentInventoryCount": len(appointment_ids),
        "providerAppointmentCoverageComplete": True,
        "localCoverageComplete": True,
        "rawRecipientStoredLocally": False,
    }


def execute(
    request_id: object,
    subject_ref: object,
    db_path: Path | str | None = None,
) -> dict:
    rid = data_subject_rights._request_id(request_id)
    row = data_subject_rights._request(rid, db_path)
    if str(row["status"]) not in {"open", "in_progress"}:
        raise RuntimeError("demande non exécutable")
    request_type = str(row["request_type"])
    if request_type not in SUPPORTED_RIGHTS:
        raise NotImplementedError("type de droit non pris en charge par cet adaptateur")
    if data_subject_rights._adapter_executed(rid, ADAPTER, db_path):
        raise RuntimeError("adaptateur déjà exécuté pour cette demande")

    raw_ref = str(subject_ref or "").strip()
    provider_ref = _verify_mercure_subject(row, raw_ref, db_path)
    appointment_ids = _appointment_inventory(provider_ref)

    if request_type in {"access", "portability"}:
        data = snapshot_appointments(appointment_ids)
        evidence = {
            "requestId": rid,
            "requestType": request_type,
            "adapter": ADAPTER,
            "appointmentInventoryCount": len(appointment_ids),
            "recordCount": int(data["recordCount"]),
            "providerAppointmentCoverageComplete": True,
            "localCoverageComplete": True,
            "exportHash": hashlib.sha256(
                json.dumps(
                    data,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
        }
        execution_id = data_subject_rights._audit_execution(
            row,
            ADAPTER,
            "export_complete",
            evidence,
            db_path,
        )
        return {
            "ok": True,
            "requestId": rid,
            "requestType": request_type,
            "adapter": ADAPTER,
            "format": "application/json",
            "data": data,
            "executionId": execution_id,
            "requestStatus": "in_progress",
            "requestComplete": False,
        }

    erased = review_followup_privacy.erase_appointments(rid, appointment_ids)
    if int(erased.get("remainingActiveRows") or 0):
        raise RuntimeError("effacement review_followup incomplet")
    evidence = {
        "requestId": rid,
        "requestType": request_type,
        "adapter": ADAPTER,
        "appointmentInventoryCount": len(appointment_ids),
        "appointmentSetHash": str(erased.get("appointmentSetHash") or ""),
        "affectedRows": int(erased.get("affectedRows") or 0),
        "remainingActiveRows": 0,
        "providerAppointmentCoverageComplete": True,
    }
    execution_id = data_subject_rights._audit_execution(
        row,
        ADAPTER,
        "erasure_complete",
        evidence,
        db_path,
    )
    return {
        "ok": True,
        "requestId": rid,
        "requestType": request_type,
        "adapter": ADAPTER,
        **erased,
        "executionId": execution_id,
        "requestStatus": "in_progress",
        "requestComplete": False,
    }


def capability() -> dict:
    return {
        "adapter": ADAPTER,
        "bound": True,
        "partial": False,
        "supportedRights": list(SUPPORTED_RIGHTS),
        "requiresVerifiedMercureSubject": True,
        "acceptsVerifiedMercureBinding": True,
        "requiresCompleteProviderAppointmentInventory": True,
        "rawRecipientStoredLocally": False,
        "rawSubjectPersistedByAdapter": False,
        "auditStoresEvidenceHashOnly": True,
        "coveredStores": ["review_followup"],
    }
