from __future__ import annotations

import hashlib
import json
from pathlib import Path

import contact_request
import data_subject_rights


ADAPTER="contact_requests"
SUPPORTED_RIGHTS=("access","portability","erasure")


def _email(value: object) -> str:
    return contact_request._email(value)


def execute(
    request_id: object,
    subject_ref: object,
    db_path: Path | str | None = None,
) -> dict:
    """Execute one exact-email right against the retained contact-request store."""
    rid=data_subject_rights._request_id(request_id)
    row=data_subject_rights._request(rid,db_path)
    if str(row["status"]) not in {"open","in_progress"}:
        raise RuntimeError("demande non exécutable")
    request_type=str(row["request_type"])
    if request_type not in SUPPORTED_RIGHTS:
        raise NotImplementedError("type de droit non pris en charge par cet adaptateur")

    raw_ref=str(subject_ref or "").strip()
    data_subject_rights._verify_subject(row,raw_ref,ADAPTER,db_path)
    email=_email(raw_ref)

    if request_type in {"access","portability"}:
        data=contact_request.privacy_snapshot(email)
        evidence={
            "requestId":rid,
            "requestType":request_type,
            "adapter":ADAPTER,
            "requestCount":int(data["requestCount"]),
            "exportHash":hashlib.sha256(
                json.dumps(
                    data,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",",":"),
                ).encode("utf-8")
            ).hexdigest(),
        }
        execution_id=data_subject_rights._audit_execution(
            row,ADAPTER,"export_complete",evidence,db_path
        )
        return {
            "ok":True,
            "requestId":rid,
            "requestType":request_type,
            "adapter":ADAPTER,
            "format":"application/json",
            "data":data,
            "executionId":execution_id,
            "requestStatus":"in_progress",
            "requestComplete":False,
        }

    erased=contact_request.erase_subject(email)
    if int(erased.get("remainingCount") or 0):
        raise RuntimeError("effacement contact incomplet")
    evidence={
        "requestId":rid,
        "requestType":request_type,
        "adapter":ADAPTER,
        "removedCount":int(erased.get("removedCount") or 0),
        "remainingCount":0,
        "subjectHash":hashlib.sha256(email.encode("utf-8")).hexdigest(),
    }
    execution_id=data_subject_rights._audit_execution(
        row,ADAPTER,"erasure_complete",evidence,db_path
    )
    return {
        "ok":True,
        "requestId":rid,
        "requestType":request_type,
        "adapter":ADAPTER,
        "removedCount":int(erased.get("removedCount") or 0),
        "remainingCount":0,
        "executionId":execution_id,
        "requestStatus":"in_progress",
        "requestComplete":False,
    }


def capability() -> dict:
    return {
        "adapter":ADAPTER,
        "bound":True,
        "partial":False,
        "supportedRights":list(SUPPORTED_RIGHTS),
        "subjectKind":"email",
        "retentionDays":contact_request.RETENTION_DAYS,
        "exactNormalizedEmailRequired":True,
        "rawSubjectPersistedByAdapter":False,
        "auditStoresEvidenceHashOnly":True,
    }
