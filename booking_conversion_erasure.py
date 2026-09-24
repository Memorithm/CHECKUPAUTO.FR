from __future__ import annotations

"""Replay-safe subject erasure for Mercure-backed booking conversions.

`booking_conversions` is keyed by provider appointment id, not directly by a
subject identifier. This adapter therefore deletes rows only when Mercure has
returned an appointment inventory whose appointment coverage is explicitly
complete for the submitted provider subject reference.

The receipt intentionally persists only a canonical SHA-256 of the appointment
set and counters. Raw appointment ids and subject references are not retained in
the receipt. Browser-callback synthetic conversion ids are not inferred from the
provider inventory and remain outside this adapter's proven coverage.
"""

import datetime
import hashlib
import json
import re
from typing import Iterable

import analytics_store
import booking_bridge
import mercure_rights


MAX_APPOINTMENT_IDS = 1000
_CHUNK_SIZE = 400
_REQUEST_RE = re.compile(r"^[a-zA-Z0-9._:-]{1,64}$")


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _request_id(value: object) -> str:
    request_id = str(value or "").strip()
    if not _REQUEST_RE.fullmatch(request_id):
        raise ValueError("requestId d'effacement conversion invalide")
    return request_id


def _appointment_ids(values: Iterable[object]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError("inventaire de rendez-vous invalide")
    clean: list[str] = []
    seen: set[str] = set()
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
    booking_bridge.init_db()
    with analytics_store.connect() as db:
        db.execute("PRAGMA secure_delete=ON")
        db.execute(
            """CREATE TABLE IF NOT EXISTS booking_conversion_privacy_receipt(
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
        analytics_store.DB.chmod(0o600)
    except PermissionError:
        pass


def _count_matching(db, appointment_ids: tuple[str, ...]) -> int:
    total = 0
    for start in range(0, len(appointment_ids), _CHUNK_SIZE):
        chunk = appointment_ids[start : start + _CHUNK_SIZE]
        placeholders = ",".join("?" for _ in chunk)
        total += int(
            db.execute(
                f"""SELECT COUNT(*) n FROM booking_conversions
                    WHERE provider=? AND external_id IN ({placeholders})""",
                (booking_bridge.PROVIDER, *chunk),
            ).fetchone()["n"]
        )
    return total


def _delete_matching(db, appointment_ids: tuple[str, ...]) -> int:
    affected = 0
    for start in range(0, len(appointment_ids), _CHUNK_SIZE):
        chunk = appointment_ids[start : start + _CHUNK_SIZE]
        placeholders = ",".join("?" for _ in chunk)
        cursor = db.execute(
            f"""DELETE FROM booking_conversions
                WHERE provider=? AND external_id IN ({placeholders})""",
            (booking_bridge.PROVIDER, *chunk),
        )
        affected += int(cursor.rowcount or 0)
    return affected


def erase_appointments(request_id: object, appointment_ids: Iterable[object]) -> dict:
    """Delete only provider-proven conversion rows and persist minimized evidence."""
    rid = _request_id(request_id)
    clean = _appointment_ids(appointment_ids)
    appointment_set_hash = _set_hash(clean)
    stamp = _now_iso()
    _init_receipt_store()

    with analytics_store.connect() as db:
        db.execute("PRAGMA secure_delete=ON")
        db.execute("BEGIN IMMEDIATE")
        previous = db.execute(
            """SELECT affected_rows,created_at,appointment_set_hash
               FROM booking_conversion_privacy_receipt WHERE request_id=?""",
            (rid,),
        ).fetchone()
        if previous and str(previous["appointment_set_hash"]) != appointment_set_hash:
            raise RuntimeError("inventaire Mercure modifié pour le même requestId")
        affected_now = _delete_matching(db, clean) if clean else 0
        remaining = _count_matching(db, clean) if clean else 0
        if remaining:
            raise RuntimeError("effacement booking_conversions incomplet")
        affected_total = int(previous["affected_rows"] if previous else 0) + affected_now
        created_at = str(previous["created_at"]) if previous else stamp
        evidence = {
            "requestId": rid,
            "store": "booking_conversions",
            "operation": "erase_provider_appointment_conversions",
            "appointmentSetHash": appointment_set_hash,
            "appointmentCount": len(clean),
            "affectedRows": affected_total,
            "remainingActiveRows": remaining,
        }
        canonical = json.dumps(evidence, sort_keys=True, separators=(",", ":"))
        evidence_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        db.execute(
            """INSERT INTO booking_conversion_privacy_receipt(
                 request_id,appointment_set_hash,appointment_count,affected_rows,
                 remaining_active_rows,evidence_hash,created_at,verified_at
               ) VALUES(?,?,?,?,?,?,?,?)
               ON CONFLICT(request_id) DO UPDATE SET
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
        "store": "booking_conversions",
        "operation": "erase_provider_appointment_conversions",
        "observed": True,
        "appointmentCount": len(clean),
        "appointmentSetHash": appointment_set_hash,
        "affectedRows": affected_total,
        "remainingActiveRows": remaining,
        "evidenceHash": evidence_hash,
        "verifiedAt": stamp,
        "browserSyntheticCoverageComplete": False,
    }


def erase_for_mercure_subject(request_id: object, subject_ref: object) -> dict:
    """Erase conversion rows only after complete provider appointment coverage proof."""
    rid = _request_id(request_id)
    raw_ref = str(subject_ref or "").strip()
    try:
        mercure_rights.parse_subject_ref(raw_ref)
    except ValueError:
        return {
            "store": "booking_conversions",
            "executed": False,
            "coverageComplete": False,
            "reason": "mercure_subject_reference_required",
        }

    try:
        snapshot = mercure_rights.contact_snapshot(raw_ref)
    except Exception:
        return {
            "store": "booking_conversions",
            "executed": False,
            "coverageComplete": False,
            "reason": "mercure_appointment_inventory_unavailable",
        }

    coverage = snapshot.get("coverage") or {}
    if not bool(coverage.get("appointments")):
        return {
            "store": "booking_conversions",
            "executed": False,
            "coverageComplete": False,
            "reason": "mercure_appointment_inventory_incomplete",
        }

    inventory = snapshot.get("operationalInventory") or {}
    rows = inventory.get("appointments") or []
    if not isinstance(rows, list):
        raise RuntimeError("inventaire Mercure des rendez-vous invalide")
    appointment_ids: list[str] = []
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
    with analytics_store.connect() as db:
        row = db.execute(
            """SELECT appointment_set_hash,appointment_count,affected_rows,
                      remaining_active_rows,evidence_hash,created_at,verified_at
               FROM booking_conversion_privacy_receipt WHERE request_id=?""",
            (rid,),
        ).fetchone()
    if not row:
        return None
    return {
        "requestId": rid,
        "store": "booking_conversions",
        "appointmentSetHash": str(row["appointment_set_hash"]),
        "appointmentCount": int(row["appointment_count"]),
        "affectedRows": int(row["affected_rows"]),
        "remainingActiveRows": int(row["remaining_active_rows"]),
        "evidenceHash": str(row["evidence_hash"]),
        "createdAt": str(row["created_at"]),
        "verifiedAt": str(row["verified_at"]),
    }
