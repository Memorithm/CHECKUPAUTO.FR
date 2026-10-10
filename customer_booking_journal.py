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
from sqlite_closing import ClosingConnection


class BookingJournalError(ValueError):
    pass


def database_path() -> Path:
    return Path(os.environ.get("CYBERCHECK_DATA_DIR", "/root/CyberCheckData")) / "customer-booking-intents.sqlite3"


def _connect() -> sqlite3.Connection:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10, isolation_level=None, factory=ClosingConnection)
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
    if verified is not True or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", reference):
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


def record_provider_receipt(*, account_id: str, key: object, provider_reference: str) -> None:
    """Persist the provider receipt BEFORE any fallible verification read."""
    token=_key(key)
    if not isinstance(provider_reference,str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}",provider_reference):
        raise BookingJournalError("booking_provider_confirmation_unverified")
    from contextlib import closing
    with closing(_connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            _initialize(db)
            row=db.execute("SELECT * FROM booking_request WHERE request_key=?",(token,)).fetchone()
            if row is None or not account_id or row["account_hash"]!=_digest(account_id):
                raise BookingJournalError("booking_request_not_found")
            if row["state"] not in {"reconciliation_required","confirmed"}:
                raise BookingJournalError("booking_reconciliation_required")
            if row["provider_reference"] and row["provider_reference"]!=provider_reference:
                raise BookingJournalError("booking_provider_reference_conflict")
            used=db.execute("SELECT request_key FROM booking_request WHERE provider_reference=? AND request_key<>?",(provider_reference,token)).fetchone()
            if used is not None:
                raise BookingJournalError("booking_provider_reference_conflict")
            db.execute("UPDATE booking_request SET provider_reference=?,updated_at=? WHERE request_key=?",(provider_reference,dt.datetime.now(dt.timezone.utc).isoformat(),token))
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise


def pending_provider_reference(*, account_id: str, key: object) -> str:
    """Internal account-scoped recovery lookup, not a browser confirmation token."""
    token=_key(key)
    from contextlib import closing
    with closing(_connect()) as db:
        _initialize(db)
        row=db.execute("SELECT * FROM booking_request WHERE request_key=?",(token,)).fetchone()
    if row is None or not account_id or row["account_hash"]!=_digest(account_id):
        raise BookingJournalError("booking_request_not_found")
    return row["provider_reference"]


def _count_and_delete(predicate: str, args: tuple, *, dry_run: bool) -> int:
    from contextlib import closing
    with closing(_connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            _initialize(db)
            count = int(db.execute(f"SELECT COUNT(*) FROM booking_request WHERE {predicate}", args).fetchone()[0])
            if count and not dry_run:
                db.execute(f"DELETE FROM booking_request WHERE {predicate}", args)
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
    return count


def erase_account(account_id: str, *, dry_run: bool = False) -> int:
    """Remove every journal row bound to one erased customer account."""
    if not account_id:
        raise BookingJournalError("booking_request_invalid")
    return _count_and_delete("account_hash=?", (_digest(account_id),), dry_run=dry_run)


def remaining_for_account(account_id: str) -> int:
    return _count_and_delete("account_hash=?", (_digest(account_id),), dry_run=True)


def purge_abandoned(cutoff_iso: str, *, dry_run: bool = False) -> int:
    """Remove 'prepared' rows (no provider write ever attempted) older than cutoff.

    Rows awaiting reconciliation are never purged automatically: an ambiguous
    provider write must be reconciled first.
    """
    return _count_and_delete("state='prepared' AND updated_at<?", (str(cutoff_iso),), dry_run=dry_run)


def purge_confirmed(cutoff_iso: str, *, dry_run: bool = False) -> int:
    """Remove confirmed rows older than an operator-approved retention cutoff."""
    return _count_and_delete("state='confirmed' AND updated_at<?", (str(cutoff_iso),), dry_run=dry_run)
