from __future__ import annotations

import datetime
import hashlib
import json
import re
from pathlib import Path

import compliance_store


_REQUEST_RE = re.compile(r"^[0-9a-f]{32}$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _request_id(value: object) -> str:
    raw = str(value or "").strip().lower()
    if not _REQUEST_RE.fullmatch(raw):
        raise ValueError("requestId de preuve provider invalide")
    return raw


def _hash(value: object, name: str) -> str:
    raw = str(value or "").strip().lower()
    if not _HASH_RE.fullmatch(raw):
        raise ValueError(f"{name} invalide")
    return raw


def _nonnegative(value: object, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} invalide")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} invalide") from exc
    if result < 0:
        raise ValueError(f"{name} invalide")
    return result


def _normalize_receipt(receipt: object, expected_store: str) -> dict:
    if not isinstance(receipt, dict):
        raise ValueError("reçu store invalide")
    if str(receipt.get("store") or "") != expected_store:
        raise ValueError("store de reçu inattendu")
    remaining = _nonnegative(
        receipt.get("remainingActiveRows"),
        "remainingActiveRows",
    )
    if remaining != 0:
        raise RuntimeError("effacement store incomplet")
    return {
        "store": expected_store,
        "appointmentSetHash": _hash(
            receipt.get("appointmentSetHash"),
            "appointmentSetHash",
        ),
        "appointmentCount": _nonnegative(
            receipt.get("appointmentCount"),
            "appointmentCount",
        ),
        "affectedRows": _nonnegative(
            receipt.get("affectedRows"),
            "affectedRows",
        ),
        "remainingActiveRows": remaining,
        "storeEvidenceHash": _hash(
            receipt.get("evidenceHash"),
            "evidenceHash",
        ),
    }


def _init(db_path: Path | str | None = None) -> None:
    compliance_store.init_db(db_path)
    with compliance_store.connect(db_path) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS provider_erasure_completion(
              request_id TEXT PRIMARY KEY,
              appointment_set_hash TEXT NOT NULL,
              appointment_count INTEGER NOT NULL,
              review_evidence_hash TEXT NOT NULL,
              booking_evidence_hash TEXT NOT NULL,
              evidence_hash TEXT NOT NULL,
              completed_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_provider_erasure_completed
              ON provider_erasure_completion(completed_at,request_id);
            """
        )


def record(
    request_id: object,
    review_receipt: object,
    booking_receipt: object,
    db_path: Path | str | None = None,
) -> dict:
    """Record minimized proof that both provider-keyed local stores are empty."""
    rid = _request_id(request_id)
    review = _normalize_receipt(review_receipt, "review_followup")
    booking = _normalize_receipt(booking_receipt, "booking_conversions")
    if review["appointmentSetHash"] != booking["appointmentSetHash"]:
        raise RuntimeError("empreintes d'inventaire provider divergentes")
    if review["appointmentCount"] != booking["appointmentCount"]:
        raise RuntimeError("comptages d'inventaire provider divergents")

    _init(db_path)
    with compliance_store.connect(db_path) as db:
        request = db.execute(
            """SELECT request_type,status FROM rights_requests
               WHERE request_id=?""",
            (rid,),
        ).fetchone()
        if not request:
            raise LookupError("demande inconnue")
        if str(request["request_type"]) != "erasure":
            raise ValueError("preuve provider réservée à l'effacement")
        if str(request["status"]) not in {"open", "in_progress"}:
            raise RuntimeError("demande non exécutable")

        evidence = {
            "requestId": rid,
            "operation": "provider_keyed_erasure_complete",
            "appointmentSetHash": review["appointmentSetHash"],
            "appointmentCount": review["appointmentCount"],
            "reviewEvidenceHash": review["storeEvidenceHash"],
            "bookingEvidenceHash": booking["storeEvidenceHash"],
            "reviewRemainingActiveRows": 0,
            "bookingRemainingActiveRows": 0,
        }
        canonical = json.dumps(
            evidence,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        evidence_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        stamp = _now_iso()

        db.execute("BEGIN IMMEDIATE")
        previous = db.execute(
            """SELECT appointment_set_hash,appointment_count,evidence_hash,completed_at
               FROM provider_erasure_completion WHERE request_id=?""",
            (rid,),
        ).fetchone()
        if previous:
            if str(previous["appointment_set_hash"]) != review["appointmentSetHash"]:
                raise RuntimeError("preuve provider déjà liée à un autre inventaire")
            if int(previous["appointment_count"]) != review["appointmentCount"]:
                raise RuntimeError("preuve provider déjà liée à un autre comptage")
            if str(previous["evidence_hash"]) == evidence_hash:
                return {
                    **evidence,
                    "evidenceHash": evidence_hash,
                    "completedAt": str(previous["completed_at"]),
                    "reused": True,
                    "rawAppointmentIdsPersisted": False,
                }

        db.execute(
            """INSERT INTO provider_erasure_completion(
                 request_id,appointment_set_hash,appointment_count,
                 review_evidence_hash,booking_evidence_hash,evidence_hash,completed_at
               ) VALUES(?,?,?,?,?,?,?)
               ON CONFLICT(request_id) DO UPDATE SET
                 review_evidence_hash=excluded.review_evidence_hash,
                 booking_evidence_hash=excluded.booking_evidence_hash,
                 evidence_hash=excluded.evidence_hash,
                 completed_at=excluded.completed_at""",
            (
                rid,
                review["appointmentSetHash"],
                review["appointmentCount"],
                review["storeEvidenceHash"],
                booking["storeEvidenceHash"],
                evidence_hash,
                stamp,
            ),
        )

    return {
        **evidence,
        "evidenceHash": evidence_hash,
        "completedAt": stamp,
        "reused": False,
        "rawAppointmentIdsPersisted": False,
    }


def status(
    request_id: object,
    db_path: Path | str | None = None,
) -> dict | None:
    rid = _request_id(request_id)
    _init(db_path)
    with compliance_store.connect(db_path) as db:
        row = db.execute(
            """SELECT appointment_set_hash,appointment_count,
                      review_evidence_hash,booking_evidence_hash,
                      evidence_hash,completed_at
               FROM provider_erasure_completion WHERE request_id=?""",
            (rid,),
        ).fetchone()
    if not row:
        return None
    return {
        "requestId": rid,
        "complete": True,
        "appointmentSetHash": str(row["appointment_set_hash"]),
        "appointmentCount": int(row["appointment_count"]),
        "reviewEvidenceHash": str(row["review_evidence_hash"]),
        "bookingEvidenceHash": str(row["booking_evidence_hash"]),
        "evidenceHash": str(row["evidence_hash"]),
        "completedAt": str(row["completed_at"]),
        "rawAppointmentIdsPersisted": False,
    }

def statuses(
    request_ids: object,
    db_path: Path | str | None = None,
) -> list[dict]:
    """Read a bounded set of completion proofs without exposing appointment ids."""
    if isinstance(request_ids, (str, bytes)) or not isinstance(request_ids, (list, tuple, set)):
        raise ValueError("liste de demandes provider invalide")
    clean: list[str] = []
    seen: set[str] = set()
    for value in request_ids:
        rid = _request_id(value)
        if rid in seen:
            continue
        seen.add(rid)
        clean.append(rid)
        if len(clean) > 500:
            raise ValueError("trop de demandes provider")
    if not clean:
        return []

    _init(db_path)
    placeholders = ",".join("?" for _ in clean)
    with compliance_store.connect(db_path) as db:
        rows = db.execute(
            f"""SELECT request_id,appointment_set_hash,appointment_count,
                       review_evidence_hash,booking_evidence_hash,
                       evidence_hash,completed_at
                FROM provider_erasure_completion
                WHERE request_id IN ({placeholders})
                ORDER BY completed_at DESC,request_id""",
            clean,
        ).fetchall()
    return [
        {
            "requestId": str(row["request_id"]),
            "complete": True,
            "appointmentSetHash": str(row["appointment_set_hash"]),
            "appointmentCount": int(row["appointment_count"]),
            "reviewEvidenceHash": str(row["review_evidence_hash"]),
            "bookingEvidenceHash": str(row["booking_evidence_hash"]),
            "evidenceHash": str(row["evidence_hash"]),
            "completedAt": str(row["completed_at"]),
            "rawAppointmentIdsPersisted": False,
        }
        for row in rows
    ]
