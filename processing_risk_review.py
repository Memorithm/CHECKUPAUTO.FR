from __future__ import annotations

import hashlib
import hmac
import json
import re
from pathlib import Path

import compliance_operations
import compliance_store


REVIEW_STATUSES = {"in_progress", "approved", "changes_required"}
_VOLATILE_ACTIVITY_FIELDS = {"createdAt", "updatedAt", "reviewOverdue"}
_MAX_EVIDENCE_BYTES = 1024 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _activity_id(value: object) -> str:
    raw = str(value or "").strip()
    if not raw or len(raw) > 64:
        raise ValueError("activityId invalide")
    return raw


def _expected_hash(value: object) -> str:
    raw = str(value or "").strip().lower()
    if not _SHA256_RE.fullmatch(raw):
        raise ValueError("empreinte d'activité invalide")
    return raw


def _review_status(value: object, name: str) -> str:
    raw = str(value or "").strip()
    if raw not in REVIEW_STATUSES:
        raise ValueError(f"{name} invalide")
    return raw


def _evidence_digest(value: object) -> str:
    if isinstance(value, bytes):
        raw = value
    else:
        raw = str(value or "").encode("utf-8")
    if not raw or len(raw) > _MAX_EVIDENCE_BYTES:
        raise ValueError("preuve de revue invalide")
    return hashlib.sha256(raw).hexdigest()


def _stable_activity(row: dict) -> dict:
    return {
        key: value
        for key, value in row.items()
        if key not in _VOLATILE_ACTIVITY_FIELDS
    }


def activity_hash(row: dict) -> str:
    canonical = json.dumps(
        _stable_activity(row),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _activity(activity_id: str, db_path: Path | str | None = None) -> dict:
    for row in compliance_operations.processing_activities(db_path):
        if str(row.get("id") or "") == activity_id:
            return row
    raise LookupError("activité de traitement inconnue")


def init_db(db_path: Path | str | None = None) -> None:
    compliance_operations.init_db(db_path)
    with compliance_store.connect(db_path) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS processing_risk_review(
              activity_id TEXT PRIMARY KEY,
              activity_hash TEXT NOT NULL,
              security_status TEXT NOT NULL,
              privacy_status TEXT NOT NULL,
              source_evidence_hash TEXT NOT NULL,
              review_evidence_hash TEXT NOT NULL,
              reviewed_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_processing_risk_reviewed
              ON processing_risk_review(reviewed_at,activity_id);
            """
        )


def record_review(
    activity_id: object,
    *,
    expected_activity_hash: object,
    security_status: object,
    privacy_status: object,
    evidence: object,
    db_path: Path | str | None = None,
) -> dict:
    """Record a bounded security/privacy review for one active high-risk activity.

    The review is bound to the exact substantive activity payload through a
    SHA-256 digest. The raw evidence document is never persisted; only its hash
    and a hash of the complete review proof are stored. If the processing
    activity changes after an operator reviewed it, status() marks the review
    stale and readiness fails closed.
    """
    aid = _activity_id(activity_id)
    expected = _expected_hash(expected_activity_hash)
    security = _review_status(security_status, "securityStatus")
    privacy = _review_status(privacy_status, "privacyStatus")
    source_evidence_hash = _evidence_digest(evidence)

    row = _activity(aid, db_path)
    if str(row.get("status") or "") != "active":
        raise RuntimeError("activité inactive")
    if str(row.get("riskLevel") or "") != "high":
        raise RuntimeError("revue renforcée réservée aux activités à risque élevé")
    current_hash = activity_hash(row)
    if not hmac.compare_digest(expected, current_hash):
        raise RuntimeError("l'activité a changé depuis la revue")

    reviewed_at = compliance_operations._now_iso()
    evidence_payload = {
        "activityId": aid,
        "activityHash": current_hash,
        "securityStatus": security,
        "privacyStatus": privacy,
        "sourceEvidenceHash": source_evidence_hash,
        "reviewedAt": reviewed_at,
    }
    review_evidence_hash = hashlib.sha256(
        json.dumps(evidence_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    init_db(db_path)
    with compliance_store.connect(db_path) as db:
        db.execute(
            """INSERT INTO processing_risk_review(
                 activity_id,activity_hash,security_status,privacy_status,
                 source_evidence_hash,review_evidence_hash,reviewed_at
               ) VALUES(?,?,?,?,?,?,?)
               ON CONFLICT(activity_id) DO UPDATE SET
                 activity_hash=excluded.activity_hash,
                 security_status=excluded.security_status,
                 privacy_status=excluded.privacy_status,
                 source_evidence_hash=excluded.source_evidence_hash,
                 review_evidence_hash=excluded.review_evidence_hash,
                 reviewed_at=excluded.reviewed_at""",
            (
                aid,
                current_hash,
                security,
                privacy,
                source_evidence_hash,
                review_evidence_hash,
                reviewed_at,
            ),
        )
    return status(db_path)


def status(db_path: Path | str | None = None) -> dict:
    """Return fail-closed review readiness for active high-risk processing."""
    init_db(db_path)
    activities = [
        row
        for row in compliance_operations.processing_activities(db_path)
        if str(row.get("status") or "") == "active"
        and str(row.get("riskLevel") or "") == "high"
    ]
    with compliance_store.connect(db_path) as db:
        review_rows = db.execute(
            """SELECT activity_id,activity_hash,security_status,privacy_status,
                      source_evidence_hash,review_evidence_hash,reviewed_at
               FROM processing_risk_review"""
        ).fetchall()
    reviews = {str(row["activity_id"]): row for row in review_rows}

    result_rows: list[dict] = []
    blockers: list[dict] = []
    for activity in activities:
        aid = str(activity.get("id") or "")
        current_hash = activity_hash(activity)
        review = reviews.get(aid)
        attested_hash = str(review["activity_hash"]) if review else ""
        stale = bool(review) and not hmac.compare_digest(attested_hash, current_hash)
        security = str(review["security_status"]) if review else "not_reviewed"
        privacy = str(review["privacy_status"]) if review else "not_reviewed"
        reviewed_at = str(review["reviewed_at"]) if review else ""
        source_evidence_hash = str(review["source_evidence_hash"]) if review else ""
        review_evidence_hash = str(review["review_evidence_hash"]) if review else ""

        if stale:
            blockers.append(
                {
                    "type": "processing_risk_review_stale",
                    "id": aid,
                    "name": str(activity.get("name") or ""),
                }
            )
        else:
            if security != "approved":
                blockers.append(
                    {
                        "type": "processing_security_review_not_approved",
                        "id": aid,
                        "name": str(activity.get("name") or ""),
                    }
                )
            if privacy != "approved":
                blockers.append(
                    {
                        "type": "processing_privacy_review_not_approved",
                        "id": aid,
                        "name": str(activity.get("name") or ""),
                    }
                )

        result_rows.append(
            {
                "activityId": aid,
                "name": str(activity.get("name") or ""),
                "currentActivityHash": current_hash,
                "reviewedActivityHash": attested_hash,
                "securityStatus": security,
                "privacyStatus": privacy,
                "stale": stale,
                "reviewedAt": reviewed_at,
                "sourceEvidenceHash": source_evidence_hash,
                "reviewEvidenceHash": review_evidence_hash,
            }
        )

    return {
        "required": bool(activities),
        "ready": not blockers,
        "highRiskActivityCount": len(activities),
        "reviewedActivityCount": sum(1 for row in result_rows if row["reviewedAt"]),
        "blockerCount": len(blockers),
        "blockers": blockers,
        "activities": result_rows,
        "rawEvidencePersisted": False,
    }
