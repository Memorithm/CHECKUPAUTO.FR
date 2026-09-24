from __future__ import annotations

import datetime
import hashlib
import json
import re
from pathlib import Path

import compliance_store
import data_subject_rights
import retention_enforcement
import withdrawal_service


ADAPTER = "withdrawal_evidence"
SUPPORTED_RIGHTS = ("access", "portability", "erasure")
RETENTION_RULE = "withdrawal_evidence"


def _email(value: object) -> str:
    raw = str(value or "").strip()
    if len(raw) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", raw):
        raise ValueError("subjectRef e-mail invalide")
    return raw.lower()


def _email_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _timestamp(value: object) -> datetime.datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed.astimezone(datetime.timezone.utc)


def snapshot(subject_email: object, db_path: Path | str | None = None) -> dict:
    """Export locally stored withdrawal evidence for one exact receipt e-mail.

    The lookup deliberately uses the persisted e-mail hash. A sent receipt may
    have had its clear-text delivery address removed already, but its original
    hash remains queryable for a data-subject export. This does not prove that
    the e-mail is the subject's only historical identity, so the adapter never
    claims subject-wide completeness.
    """
    email = _email(subject_email)
    withdrawal_service.init_db(db_path)
    with compliance_store.connect(db_path) as db:
        rows = db.execute(
            """SELECT request_id,contract_ref,first_name,last_name,receipt_email,
                      submitted_at,declaration_hash,contract_match,
                      contract_concluded_at,standard_deadline_at,
                      standard_deadline_passed,immediate_performance_requested,
                      receipt_status,receipt_attempts,receipt_sent_at
               FROM withdrawal_requests
               WHERE receipt_email_hash=?
               ORDER BY submitted_at,request_id""",
            (_email_hash(email),),
        ).fetchall()

    records = [
        {
            "requestId": str(row["request_id"]),
            "contractRef": str(row["contract_ref"]),
            "firstName": str(row["first_name"]),
            "lastName": str(row["last_name"]),
            "receiptEmail": str(row["receipt_email"]),
            "submittedAt": str(row["submitted_at"]),
            "declarationHash": str(row["declaration_hash"]),
            "contractMatched": bool(row["contract_match"]),
            "contractConcludedAt": str(row["contract_concluded_at"]),
            "standardDeadlineAt": str(row["standard_deadline_at"]),
            "standardDeadlinePassed": bool(row["standard_deadline_passed"]),
            "immediatePerformanceRequested": bool(
                row["immediate_performance_requested"]
            ),
            "receiptStatus": str(row["receipt_status"]),
            "receiptAttempts": int(row["receipt_attempts"] or 0),
            "receiptSentAt": str(row["receipt_sent_at"]),
        }
        for row in rows
    ]
    return {
        "records": records,
        "recordCount": len(records),
        "lookup": "receipt_email_hash",
        "localLookupCompleteForEmail": True,
        "subjectCoverageComplete": False,
        "partial": True,
    }


def erase(subject_email: object, db_path: Path | str | None = None) -> dict:
    """Erase expired evidence for one verified receipt e-mail, fail-closed.

    Withdrawal evidence can be retained only under an explicitly configured and
    legally reviewed retention policy. Rows still inside that validated window
    are retained; rows with malformed timestamps are also retained rather than
    guessed expired. Historical or alternate subject e-mails are never inferred.
    """
    email = _email(subject_email)
    retention = retention_enforcement.policy(RETENTION_RULE, db_path)
    if not retention.get("ready") or not retention.get("legalReviewConfirmed"):
        raise RuntimeError("politique de conservation des rétractations non prête")
    try:
        active_days = int(retention.get("activeDays"))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("durée de conservation des rétractations invalide") from exc
    if active_days < 1:
        raise RuntimeError("durée de conservation des rétractations invalide")

    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(days=active_days)
    digest = _email_hash(email)
    withdrawal_service.init_db(db_path)
    with compliance_store.connect(db_path) as db:
        rows = db.execute(
            """SELECT request_id,submitted_at FROM withdrawal_requests
               WHERE receipt_email_hash=? ORDER BY submitted_at,request_id""",
            (digest,),
        ).fetchall()
        expired_ids: list[str] = []
        malformed = 0
        for row in rows:
            submitted = _timestamp(row["submitted_at"])
            if submitted is None:
                malformed += 1
            elif submitted < cutoff:
                expired_ids.append(str(row["request_id"]))
        if expired_ids:
            db.executemany(
                "DELETE FROM withdrawal_requests WHERE request_id=? AND receipt_email_hash=?",
                [(request_id, digest) for request_id in expired_ids],
            )
        remaining = int(
            db.execute(
                "SELECT COUNT(*) n FROM withdrawal_requests WHERE receipt_email_hash=?",
                (digest,),
            ).fetchone()["n"]
        )

    matched = len(rows)
    erased = len(expired_ids)
    retained = remaining
    return {
        "retentionRule": RETENTION_RULE,
        "retentionPolicyReady": True,
        "legalReviewConfirmed": True,
        "activeDays": active_days,
        "cutoffAt": cutoff.isoformat(timespec="seconds"),
        "matchedCount": matched,
        "erasedCount": erased,
        "retainedCount": retained,
        "retainedMalformedTimestampCount": malformed,
        "lookup": "receipt_email_hash",
        "localLookupCompleteForEmail": True,
        "subjectCoverageComplete": False,
        "partial": True,
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

    raw_ref = str(subject_ref or "").strip()
    data_subject_rights._verify_subject(row, raw_ref, ADAPTER, db_path)
    request_type = str(row["request_type"])
    if request_type not in SUPPORTED_RIGHTS:
        raise NotImplementedError("type de droit non pris en charge par cet adaptateur")
    if not data_subject_rights._adapter_can_retry_partial(rid, ADAPTER, db_path):
        raise RuntimeError("adaptateur déjà exécuté pour cette demande")

    if request_type == "erasure":
        data = erase(raw_ref, db_path)
        evidence = {
            "requestId": rid,
            "requestType": request_type,
            "adapter": ADAPTER,
            "retentionRule": RETENTION_RULE,
            "retentionPolicyReady": True,
            "legalReviewConfirmed": True,
            "activeDays": int(data["activeDays"]),
            "matchedCount": int(data["matchedCount"]),
            "erasedCount": int(data["erasedCount"]),
            "retainedCount": int(data["retainedCount"]),
            "retainedMalformedTimestampCount": int(
                data["retainedMalformedTimestampCount"]
            ),
            "localLookupCompleteForEmail": True,
            "subjectCoverageComplete": False,
        }
        action = "erase_retention_applied"
    else:
        data = snapshot(raw_ref, db_path)
        canonical = json.dumps(
            data,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        evidence = {
            "requestId": rid,
            "requestType": request_type,
            "adapter": ADAPTER,
            "recordCount": int(data["recordCount"]),
            "localLookupCompleteForEmail": True,
            "subjectCoverageComplete": False,
            "exportHash": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        }
        action = "export"

    execution_id = data_subject_rights._audit_execution(
        row,
        ADAPTER,
        action,
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


def capability() -> dict:
    return {
        "adapter": ADAPTER,
        "supportedRights": list(SUPPORTED_RIGHTS),
        "subjectReference": "exact_receipt_email",
        "lookup": "sha256_normalized_email",
        "clearSubjectReferencePersistedByAdapter": False,
        "localLookupCompleteForEmail": True,
        "subjectCoverageComplete": False,
        "erasureImplemented": True,
        "erasureRequiresReadyValidatedRetentionPolicy": True,
        "retentionRule": RETENTION_RULE,
        "limitation": "historical_or_alternate_subject_email_not_inferred",
    }
