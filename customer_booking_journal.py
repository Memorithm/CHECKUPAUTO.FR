"""Durable fail-closed reservation journal; no Mercure write or payment call.

An ambiguous provider write remains pending reconciliation. It is NEVER retried
blindly with the same key or replaced with another key.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path


class BookingJournalError(ValueError):
    pass


def database_path() -> Path:
    return Path(os.environ.get("CYBERCHECK_DATA_DIR", "/root/CyberCheckData")) / "customer-booking-intents.sqlite3"


def _connect() -> sqlite3.Connection:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=10000")
    return db


def _initialize(db: sqlite3.Connection) -> None:
    db.execute("""CREATE TABLE IF NOT EXISTS booking_request (
      request_key TEXT PRIMARY KEY,
      account_hash TEXT NOT NULL,
      request_hash TEXT NOT NULL,
      state TEXT NOT NULL CHECK(state IN ('prepared','reconciliation_required','confirmed')),
      provider_reference TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    )""")


def _key(value: object) -> str:
    raw = str(value or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,128}", raw):
        raise BookingJournalError("booking_idempotency_key_invalid")
    return raw


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    ).hexdigest()


def prepare(*, account_id: str, key: object, request: dict) -> dict:
    """Atomically bind one idempotency key to one account and exact request."""
    token = _key(key)
    if not account_id or not isinstance(request, dict):
        raise BookingJournalError("booking_request_invalid")
    account_hash = _digest(account_id)
    request_hash = _digest(request)
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            _initialize(db)
            db.execute("""INSERT OR IGNORE INTO booking_request
              (request_key,account_hash,request_hash,state,created_at,updated_at)
              VALUES (?,?,?,'prepared',?,?)""",
              (token,account_hash,request_hash,now,now))
            row = db.execute("SELECT * FROM booking_request WHERE request_key=?", (token,)).fetchone()
            if row["account_hash"] != account_hash or row["request_hash"] != request_hash:
                raise BookingJournalError("booking_idempotency_conflict")
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
    return {"state": row["state"], "requestKey": token,
            "confirmed": row["state"] == "confirmed"}


def require_reconciliation(*, account_id: str, key: object) -> dict:
    """Claim the external write once. Timeout or crash leaves reconciliation required."""
    token = _key(key)
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            _initialize(db)
            row = db.execute("SELECT * FROM booking_request WHERE request_key=?", (token,)).fetchone()
            if row is None or row["account_hash"] != _digest(account_id):
                raise BookingJournalError("booking_request_not_found")
            if row["state"] != "prepared":
                raise BookingJournalError("booking_reconciliation_required")
            db.execute("UPDATE booking_request SET state='reconciliation_required', updated_at=? WHERE request_key=?",
                       (dt.datetime.now(dt.timezone.utc).isoformat(), token))
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
    return {"state": "reconciliation_required", "confirmed": False}


def confirm_verified(*, account_id: str, key: object, provider_reference: object,
                     verified: bool) -> dict:
    """Confirm only after an independent authoritative provider read.

    This does not perform a provider lookup itself. The future connector must
    supply evidence from an authenticated Mercure read, never a browser callback.
    """
    token = _key(key)
    reference = str(provider_reference or "").strip()
    if not verified or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", reference):
        raise BookingJournalError("booking_provider_confirmation_unverified")
    if not account_id:
        raise BookingJournalError("booking_request_invalid")
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            _initialize(db)
            row = db.execute("SELECT * FROM booking_request WHERE request_key=?", (token,)).fetchone()
            if row is None or row["account_hash"] != _digest(account_id):
                raise BookingJournalError("booking_request_not_found")
            if row["state"] == "confirmed":
                if row["provider_reference"] != reference:
                    raise BookingJournalError("booking_provider_reference_conflict")
            elif row["state"] != "reconciliation_required":
                raise BookingJournalError("booking_reconciliation_required")
            else:
                db.execute("""UPDATE booking_request
                    SET state='confirmed', provider_reference=?, updated_at=?
                    WHERE request_key=? AND state='reconciliation_required'""",
                    (reference, dt.datetime.now(dt.timezone.utc).isoformat(), token))
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
    return {"state": "confirmed", "confirmed": True, "providerReference": reference}


def status(*, account_id: str, key: object) -> dict:
    """Read only the requesting account's booking state, never another account's."""
    token = _key(key)
    with _connect() as db:
        _initialize(db)
        row = db.execute("SELECT * FROM booking_request WHERE request_key=?", (token,)).fetchone()
    if row is None or not account_id or row["account_hash"] != _digest(account_id):
        raise BookingJournalError("booking_request_not_found")
    return {"state": row["state"], "confirmed": row["state"] == "confirmed",
            "providerReference": row["provider_reference"] if row["state"] == "confirmed" else ""}
