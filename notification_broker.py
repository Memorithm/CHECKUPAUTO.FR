from __future__ import annotations

import datetime
import hashlib
import os
import re
import sqlite3
from pathlib import Path

import email_gateway as email_transport
import apns_gateway as push_transport

DATA_DIR = Path(os.environ.get("CYBERCHECK_DATA_DIR", "/root/CyberCheckData"))
DB = DATA_DIR / "notification-broker.sqlite3"
LEASE_SECONDS = 120
MAX_ERROR = 300


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _now_iso() -> str:
    return _now().isoformat(timespec="seconds")


def _text(value: object, name: str, limit: int) -> str:
    clean = str(value or "").strip()
    if not clean or len(clean) > limit:
        raise ValueError(f"{name} invalide")
    return clean

def _recipient_hash(recipient: str) -> str:
    return hashlib.sha256(recipient.strip().lower().encode("utf-8")).hexdigest()


def _safe_error(exc: Exception) -> str:
    raw = f"{type(exc).__name__}: {exc}"
    return re.sub(r"[^\s<>]+@[^\s<>]+", "[email]", raw)[:MAX_ERROR]


def _delivery_key(channel: str, category: str, reference: str, recipient: str) -> str:
    material = "|".join((channel, category, reference, recipient.strip().lower()))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        DATA_DIR.chmod(0o700)
    except PermissionError:
        pass
    db = sqlite3.connect(DB, timeout=10)
    db.row_factory = sqlite3.Row
    return db


def init_db() -> None:
    with connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS notification_delivery(
          idempotency_key TEXT PRIMARY KEY,
          channel TEXT NOT NULL,
          category TEXT NOT NULL,
          reference TEXT NOT NULL,
          recipient_hash TEXT NOT NULL,
          status TEXT NOT NULL,
          attempts INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL,
          last_attempt_at TEXT NOT NULL DEFAULT '',
          sent_at TEXT NOT NULL DEFAULT '',
          last_error TEXT NOT NULL DEFAULT ''
        )""")
        db.execute("CREATE INDEX IF NOT EXISTS idx_notification_status ON notification_delivery(status, sent_at)")
    try:
        DB.chmod(0o600)
    except PermissionError:
        pass


def _lease_active(row: sqlite3.Row, now: datetime.datetime) -> bool:
    if row["status"] != "delivering" or not row["last_attempt_at"]:
        return False
    try:
        started = datetime.datetime.fromisoformat(row["last_attempt_at"])
    except ValueError:
        return False
    if started.tzinfo is None:
        started = started.replace(tzinfo=datetime.timezone.utc)
    return (now - started.astimezone(datetime.timezone.utc)).total_seconds() < LEASE_SECONDS


def _public_result(row: sqlite3.Row, *, already_sent: bool = False, in_flight: bool = False) -> dict:
    return {
        "ok": row["status"] == "sent" or already_sent or in_flight,
        "channel": row["channel"],
        "category": row["category"],
        "reference": row["reference"],
        "status": row["status"],
        "attempts": int(row["attempts"]),
        "sentAt": row["sent_at"],
        "alreadySent": already_sent,
        "inFlight": in_flight,
    }


def send_email(
    recipient: str,
    subject: str,
    text: str,
    html: str = "",
    *,
    category: str,
    reference: str,
) -> dict:
    recipient = str(recipient or "").strip()
    if not email_transport.valid_email(recipient):
        raise ValueError("Adresse destinataire invalide")
    category = _text(category, "Catégorie", 80)
    reference = _text(reference, "Référence", 160)
    key = _delivery_key("email", category, reference, recipient)
    now = _now()
    now_iso = now.isoformat(timespec="seconds")
    init_db()

    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM notification_delivery WHERE idempotency_key=?", (key,)).fetchone()
        if row and row["status"] == "sent":
            return _public_result(row, already_sent=True)
        if row and _lease_active(row, now):
            return _public_result(row, in_flight=True)
        if row is None:
            db.execute(
                """INSERT INTO notification_delivery(
                   idempotency_key,channel,category,reference,recipient_hash,status,attempts,created_at,last_attempt_at
                   ) VALUES(?,?,?,?,?,'delivering',1,?,?)""",
                (key, "email", category, reference, _recipient_hash(recipient), now_iso, now_iso),
            )
        else:
            db.execute(
                """UPDATE notification_delivery
                   SET status='delivering',attempts=attempts+1,last_attempt_at=?,last_error=''
                   WHERE idempotency_key=?""",
                (now_iso, key),
            )

    try:
        email_transport.send_email(recipient, subject, text, html)
    except Exception as exc:
        with connect() as db:
            db.execute(
                "UPDATE notification_delivery SET status='failed',last_error=? WHERE idempotency_key=?",
                (_safe_error(exc), key),
            )
        raise

    sent_at = _now_iso()
    with connect() as db:
        db.execute(
            """UPDATE notification_delivery
               SET status='sent',sent_at=?,last_error='' WHERE idempotency_key=?""",
            (sent_at, key),
        )
        row = db.execute("SELECT * FROM notification_delivery WHERE idempotency_key=?", (key,)).fetchone()
    return _public_result(row)



def send_push(
    device_token: str,
    title: str,
    body: str,
    *,
    category: str,
    reference: str,
    data: dict | None = None,
) -> dict:
    token = str(device_token or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{32,400}", token) or len(token) % 2:
        raise ValueError("Jeton APNs invalide")
    category = _text(category, "Catégorie", 80)
    reference = _text(reference, "Référence", 160)
    key = _delivery_key("push", category, reference, token)
    now = _now(); now_iso = now.isoformat(timespec="seconds")
    init_db()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM notification_delivery WHERE idempotency_key=?", (key,)).fetchone()
        if row and row["status"] == "sent":
            return _public_result(row, already_sent=True)
        if row and _lease_active(row, now):
            return _public_result(row, in_flight=True)
        if row is None:
            db.execute(
                """INSERT INTO notification_delivery(
                   idempotency_key,channel,category,reference,recipient_hash,status,attempts,created_at,last_attempt_at
                   ) VALUES(?,?,?,?,?,'delivering',1,?,?)""",
                (key, "push", category, reference, _recipient_hash(token), now_iso, now_iso),
            )
        else:
            db.execute(
                "UPDATE notification_delivery SET status='delivering',attempts=attempts+1,last_attempt_at=?,last_error='' WHERE idempotency_key=?",
                (now_iso, key),
            )
    try:
        push_transport.send(token, title, body, data=data)
    except Exception as exc:
        with connect() as db:
            db.execute("UPDATE notification_delivery SET status='failed',last_error=? WHERE idempotency_key=?", (_safe_error(exc), key))
        raise
    sent_at = _now_iso()
    with connect() as db:
        db.execute("UPDATE notification_delivery SET status='sent',sent_at=?,last_error='' WHERE idempotency_key=?", (sent_at, key))
        row = db.execute("SELECT * FROM notification_delivery WHERE idempotency_key=?", (key,)).fetchone()
    return _public_result(row)

def status(limit: int = 20) -> dict:
    init_db()
    limit = max(1, min(int(limit), 100))
    with connect() as db:
        counts = {
            row["status"]: int(row["n"])
            for row in db.execute("SELECT status,COUNT(*) n FROM notification_delivery GROUP BY status")
        }
        recent = [
            dict(row)
            for row in db.execute(
                """SELECT channel,category,reference,status,attempts,created_at,last_attempt_at,sent_at,last_error
                   FROM notification_delivery ORDER BY COALESCE(sent_at,last_attempt_at,created_at) DESC LIMIT ?""",
                (limit,),
            )
        ]
    return {
        "ok": True,
        "channels": {
            "email": email_transport.transport_status(),
            "push": push_transport.status(),
        },
        "counts": counts,
        "recent": recent,
        "privacy": "Les destinataires et le contenu des notifications ne sont pas persistés par le broker.",
    }
