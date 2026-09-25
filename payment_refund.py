"""Crash-safe operator ledger for Payline sandbox refunds.

The browser/operator never supplies the provider transaction id. It is resolved
from the verified capture evidence in SandboxJournal. An attempt is persisted
before the provider call; ambiguous attempts are never retried automatically.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import re
import sqlite3
from pathlib import Path

import payment_payline as payline
import payment_payline_private as payline_private
from payment_core import PaymentError, SandboxJournal

REASONS = {"customer_request", "booking_cancelled", "duplicate", "operator_correction"}
STATES = {"attempting", "completed", "indeterminate", "refused"}


def journal_path() -> Path:
    return Path(os.environ.get("CYBERCHECK_DATA_DIR", "/root/CyberCheckData")) / "payments.sqlite3"


def _stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _request_id(value) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{32}", value):
        raise PaymentError("refund_request_id_invalid")
    return value


def _payment_id(value) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{32}", value):
        raise PaymentError("payment_id_invalid")
    return value


def _amount(value) -> int:
    if type(value) is not int or not 1 <= value <= 9000:
        raise PaymentError("refund_amount_invalid")
    return value


def _reason(value) -> str:
    if value not in REASONS:
        raise PaymentError("refund_reason_invalid")
    return str(value)


def _sequence(request_id: str) -> str:
    return "refund_" + request_id[:24]


def _evidence(request_id: str, payment_id: str, amount_cents: int, reason: str, state: str) -> str:
    material = "\x00".join(
        ("checkupauto:payline-refund:v1", request_id, payment_id, str(amount_cents), reason, state)
    )
    return hashlib.sha256(material.encode()).hexdigest()


def _connect(path: Path):
    db = sqlite3.connect(path, timeout=5)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("""CREATE TABLE IF NOT EXISTS payment_refunds(
      request_id TEXT PRIMARY KEY,
      payment_id TEXT NOT NULL REFERENCES payment_intents(payment_id),
      provider TEXT NOT NULL CHECK(provider='payline'),
      amount_cents INTEGER NOT NULL CHECK(typeof(amount_cents)='integer' AND amount_cents BETWEEN 1 AND 9000),
      reason TEXT NOT NULL CHECK(reason IN ('customer_request','booking_cancelled','duplicate','operator_correction')),
      state TEXT NOT NULL CHECK(state IN ('attempting','completed','indeterminate','refused')),
      evidence_hash TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS payment_refunds_payment ON payment_refunds(payment_id,state)")
    db.commit()
    return db


def _public(row, *, reused=False) -> dict:
    return {
        "requestId": str(row["request_id"]),
        "paymentId": str(row["payment_id"]),
        "provider": "payline",
        "environment": "sandbox",
        "amountCents": int(row["amount_cents"]),
        "currency": "EUR",
        "reason": str(row["reason"]),
        "state": str(row["state"]),
        "evidenceHash": str(row["evidence_hash"] or ""),
        "createdAt": str(row["created_at"]),
        "updatedAt": str(row["updated_at"]),
        "reused": bool(reused),
    }


def execute(request_id: str, payment_id: str, amount_cents: int, reason: str, *, refunder=None) -> dict:
    request_id = _request_id(request_id)
    payment_id = _payment_id(payment_id)
    amount_cents = _amount(amount_cents)
    reason = _reason(reason)

    store = SandboxJournal(journal_path())
    intent = store.get(payment_id)
    if intent.provider != "payline" or intent.environment != "sandbox" or intent.state != "captured":
        raise PaymentError("captured_payline_sandbox_payment_required")
    tx = store.provider_transaction(payment_id)
    if tx["provider"] != "payline":
        raise PaymentError("captured_payline_sandbox_payment_required")
    captured = int(tx["capturedAmountCents"])
    config = payline_private.load()

    db = _connect(journal_path())
    try:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute("SELECT * FROM payment_refunds WHERE request_id=?", (request_id,)).fetchone()
        if existing is not None:
            if (
                str(existing["payment_id"]) != payment_id
                or int(existing["amount_cents"]) != amount_cents
                or str(existing["reason"]) != reason
            ):
                raise PaymentError("refund_request_replay_conflict")
            state = str(existing["state"])
            db.commit()
            if state in {"attempting", "indeterminate"}:
                raise PaymentError("refund_reconciliation_required")
            return _public(existing, reused=True)

        reserved = int(db.execute(
            """SELECT COALESCE(SUM(amount_cents),0) FROM payment_refunds
               WHERE payment_id=? AND state IN ('attempting','indeterminate','completed')""",
            (payment_id,),
        ).fetchone()[0])
        if reserved + amount_cents > captured:
            raise PaymentError("refund_amount_exceeds_remaining_capture")

        now = _stamp()
        db.execute(
            """INSERT INTO payment_refunds(
                 request_id,payment_id,provider,amount_cents,reason,state,evidence_hash,created_at,updated_at
               ) VALUES(?,?,'payline',?,?,'attempting','',?,?)""",
            (request_id, payment_id, amount_cents, reason, now, now),
        )
        db.commit()

        refund_fn = refunder or payline.refund
        try:
            refund_fn(
                intent,
                str(tx["transactionId"]),
                amount_cents,
                config,
                _sequence(request_id),
                reason.replace("_", " "),
            )
        except PaymentError as exc:
            state = "refused" if str(exc) == "payline_refund_refused" else "indeterminate"
            evidence = _evidence(request_id, payment_id, amount_cents, reason, state)
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "UPDATE payment_refunds SET state=?,evidence_hash=?,updated_at=? WHERE request_id=? AND state='attempting'",
                (state, evidence, _stamp(), request_id),
            )
            db.commit()
            if state == "indeterminate":
                raise PaymentError("refund_reconciliation_required") from None
            raise
        except Exception:
            evidence = _evidence(request_id, payment_id, amount_cents, reason, "indeterminate")
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "UPDATE payment_refunds SET state='indeterminate',evidence_hash=?,updated_at=? WHERE request_id=? AND state='attempting'",
                (evidence, _stamp(), request_id),
            )
            db.commit()
            raise PaymentError("refund_reconciliation_required") from None

        evidence = _evidence(request_id, payment_id, amount_cents, reason, "completed")
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            "UPDATE payment_refunds SET state='completed',evidence_hash=?,updated_at=? WHERE request_id=? AND state='attempting'",
            (evidence, _stamp(), request_id),
        )
        db.commit()
        row = db.execute("SELECT * FROM payment_refunds WHERE request_id=?", (request_id,)).fetchone()
        return _public(row)
    finally:
        db.close()


def activity(limit: int = 50) -> dict:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise PaymentError("refund_activity_limit_invalid")
    path = journal_path()
    if not path.is_file():
        return {
            "summary": {"total": 0, "completed": 0, "attempting": 0, "indeterminate": 0, "refused": 0},
            "refunds": [],
        }
    SandboxJournal(path)
    db = _connect(path)
    try:
        counts = {
            str(row["state"]): int(row["n"])
            for row in db.execute("SELECT state,COUNT(*) AS n FROM payment_refunds GROUP BY state").fetchall()
        }
        rows = db.execute(
            "SELECT * FROM payment_refunds ORDER BY created_at DESC,request_id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        total = int(db.execute("SELECT COUNT(*) FROM payment_refunds").fetchone()[0])
    finally:
        db.close()
    return {
        "summary": {
            "total": total,
            "completed": counts.get("completed", 0),
            "attempting": counts.get("attempting", 0),
            "indeterminate": counts.get("indeterminate", 0),
            "refused": counts.get("refused", 0),
        },
        "refunds": [_public(row) for row in rows],
    }


def capability() -> dict:
    return {
        "provider": "payline",
        "environment": "sandbox",
        "operatorRefundLedger": True,
        "providerTransactionFromVerifiedCapture": True,
        "cumulativeCaptureLimit": True,
        "ambiguousRefundRetryBlocked": True,
        "liveRefundsEnabled": False,
    }
