from __future__ import annotations

"""Replay-safe privacy erasure for the local review-follow-up store.

The review-follow-up database is keyed by Mercure appointment id, not directly
by a data subject. This adapter therefore mutates it only when Mercure has
returned an appointment inventory whose provider boundary is explicitly proven
complete for the subject. Raw appointment ids are never persisted in the
privacy receipt; only a canonical set hash is retained.
"""

import datetime
import hashlib
import json
import re
from typing import Iterable

import mercure_rights
import review_followup


MAX_APPOINTMENT_IDS = 1000
_CHUNK_SIZE = 400
_REQUEST_RE = re.compile(r"^[a-zA-Z0-9._:-]{1,64}$")


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _request_id(value: object) -> str:
    request_id = str(value or "").strip()
    if not _REQUEST_RE.fullmatch(request_id):
        raise ValueError("requestId d'effacement avis invalide")
    return request_id


def _appointment_ids(values: Iterable[object]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError("inventaire de rendez-vous invalide")
    clean = []
    seen = set()
    for value in values:
        appointment_id = str(value or "").strip()
        if not appointment_id or len(appointment_id) > 128:
            raise ValueError("identifiant de rendez-vous invalide")
        if appointment_id in seen:
            continue
        seen.add(appointment_id)
        clean.append(appointment_id)
        if len(clean) > MAX_APPOINTMENT_IDS:
            raise ValueError("inventaire de rendez-vous trop volumineux")
    return tuple(sorted(clean))


def _set_hash(appointment_ids: tuple[str, ...]) -> str:
    canonical = json.dumps(list(appointment_ids), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _init_receipt_store() -> None:
    review_followup.init_db()
    with review_followup.connect() as db:
        db.execute("PRAGMA secure_delete=ON")
        db.execute(
            """CREATE TABLE IF NOT EXISTS review_followup_privacy_receipt(
                 request_id TEXT PRIMARY KEY,
                 appointment_set_hash TEXT NOT NULL,
                 appointment_count INTEGER NOT NULL,
                 affected_rows INTEGER NOT NULL,
                 remaining_active_rows INTEGER NOT NULL,
                 evidence_hash TEXT NOT NULL,
                 created_at TEXT NOT NULL,
                 verified_at TEXT NOT NULL
               )"""
        )
    try:
        review_followup.DB.chmod(0o600)
    except PermissionError:
        pass


def _count_matching(db, appointment_ids: tuple[str, ...]) -> int:
    total = 0
    for start in range(0, len(appointment_ids), _CHUNK_SIZE):
        chunk = appointment_ids[start : start + _CHUNK_SIZE]
        placeholders = ",".join("?" for _ in chunk)
        total += int(
            db.execute(
                f"SELECT COUNT(*) n FROM review_followup WHERE appointment_id IN ({placeholders})",
                chunk,
            ).fetchone()["n"]
        )
    return total


def _delete_matching(db, appointment_ids: tuple[str, ...]) -> int:
    affected = 0
    for start in range(0, len(appointment_ids), _CHUNK_SIZE):
        chunk = appointment_ids[start : start + _CHUNK_SIZE]
        placeholders = ",".join("?" for _ in chunk)
        cursor = db.execute(
            f"DELETE FROM review_followup WHERE appointment_id IN ({placeholders})",
            chunk,
        )
        affected += int(cursor.rowcount or 0)
    return affected


def erase_appointments(request_id: object, appointment_ids: Iterable[object]) -> dict:
    """Physically erase only the exact provider-proven appointment id set.

    The local receipt is written in the same SQLite transaction as the deletion,
    so a later failure in the compliance/audit database can be retried without
    losing evidence. Replays accumulate affected rows and also remove a matching
    row if an older worker reintroduced it between attempts.
    """
    rid = _request_id(request_id)
    clean = _appointment_ids(appointment_ids)
    appointment_set_hash = _set_hash(clean)
    stamp = _now_iso()
    _init_receipt_store()

    with review_followup.connect() as db:
        db.execute("PRAGMA secure_delete=ON")
        db.execute("BEGIN IMMEDIATE")
        previous = db.execute(
            """SELECT affected_rows,created_at FROM review_followup_privacy_receipt
               WHERE request_id=?""",
            (rid,),
        ).fetchone()
        affected_now = _delete_matching(db, clean) if clean else 0
        remaining = _count_matching(db, clean) if clean else 0
        if remaining:
            raise RuntimeError("effacement review_followup incomplet")
        affected_total = int(previous["affected_rows"] if previous else 0) + affected_now
        created_at = str(previous["created_at"]) if previous else stamp
        evidence = {
            "requestId": rid,
            "store": "review_followup",
            "operation": "erase_subject_appointments",
            "appointmentSetHash": appointment_set_hash,
            "appointmentCount": len(clean),
            "affectedRows": affected_total,
            "remainingActiveRows": remaining,
        }
        canonical = json.dumps(evidence, sort_keys=True, separators=(",", ":"))
        evidence_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        db.execute(
            """INSERT INTO review_followup_privacy_receipt(
                 request_id,appointment_set_hash,appointment_count,affected_rows,
                 remaining_active_rows,evidence_hash,created_at,verified_at
               ) VALUES(?,?,?,?,?,?,?,?)
               ON CONFLICT(request_id) DO UPDATE SET
                 appointment_set_hash=excluded.appointment_set_hash,
                 appointment_count=excluded.appointment_count,
                 affected_rows=excluded.affected_rows,
                 remaining_active_rows=excluded.remaining_active_rows,
                 evidence_hash=excluded.evidence_hash,
                 verified_at=excluded.verified_at""",
            (
                rid,
                appointment_set_hash,
                len(clean),
                affected_total,
                remaining,
                evidence_hash,
                created_at,
                stamp,
            ),
        )

    return {
        "store": "review_followup",
        "operation": "erase_subject_appointments",
        "observed": True,
        "appointmentCount": len(clean),
        "appointmentSetHash": appointment_set_hash,
        "affectedRows": affected_total,
        "remainingActiveRows": remaining,
        "evidenceHash": evidence_hash,
        "verifiedAt": stamp,
    }


def erase_for_mercure_subject(request_id: object, subject_ref: object) -> dict:
    """Erase review-follow-up rows only after complete appointment coverage proof."""
    rid = _request_id(request_id)
    raw_ref = str(subject_ref or "").strip()
    try:
        mercure_rights.parse_subject_ref(raw_ref)
    except ValueError:
        return {
            "store": "review_followup",
            "executed": False,
            "coverageComplete": False,
            "reason": "mercure_subject_reference_required",
        }

    try:
        snapshot = mercure_rights.contact_snapshot(raw_ref)
    except Exception:
        return {
            "store": "review_followup",
            "executed": False,
            "coverageComplete": False,
            "reason": "mercure_appointment_inventory_unavailable",
        }

    coverage = snapshot.get("coverage") or {}
    if not bool(coverage.get("appointments")):
        return {
            "store": "review_followup",
            "executed": False,
            "coverageComplete": False,
            "reason": "mercure_appointment_inventory_incomplete",
        }

    inventory = snapshot.get("operationalInventory") or {}
    rows = inventory.get("appointments") or []
    if not isinstance(rows, list):
        raise RuntimeError("inventaire Mercure des rendez-vous invalide")
    appointment_ids = []
    for row in rows:
        if not isinstance(row, dict):
            raise RuntimeError("inventaire Mercure des rendez-vous invalide")
        appointment_id = str(row.get("appointmentId") or "").strip()
        if not appointment_id:
            raise RuntimeError("preuve Mercure de rendez-vous incomplète")
        appointment_ids.append(appointment_id)

    clean = _appointment_ids(appointment_ids)
    provider_count = int(inventory.get("appointmentCountInWindow") or 0)
    if provider_count != len(clean):
        raise RuntimeError("inventaire Mercure des rendez-vous incohérent")

    mutation = erase_appointments(rid, clean)
    return {
        **mutation,
        "executed": True,
        "coverageComplete": True,
        "reason": "",
    }


def receipt(request_id: object) -> dict | None:
    rid = _request_id(request_id)
    _init_receipt_store()
    with review_followup.connect() as db:
        row = db.execute(
            """SELECT appointment_set_hash,appointment_count,affected_rows,
                      remaining_active_rows,evidence_hash,created_at,verified_at
               FROM review_followup_privacy_receipt WHERE request_id=?""",
            (rid,),
        ).fetchone()
    if not row:
        return None
    return {
        "requestId": rid,
        "store": "review_followup",
        "appointmentSetHash": str(row["appointment_set_hash"]),
        "appointmentCount": int(row["appointment_count"]),
        "affectedRows": int(row["affected_rows"]),
        "remainingActiveRows": int(row["remaining_active_rows"]),
        "evidenceHash": str(row["evidence_hash"]),
        "createdAt": str(row["created_at"]),
        "verifiedAt": str(row["verified_at"]),
    }
