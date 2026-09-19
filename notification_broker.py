from __future__ import annotations

import datetime
import hashlib
import os
import re
import sqlite3
from pathlib import Path

import email_gateway as email_transport
import apns_gateway as push_transport
import delivery_resilience as resilience

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
        columns = {row["name"] for row in db.execute("PRAGMA table_info(notification_delivery)")}
        for name, ddl in (
            ("failure_class", "TEXT NOT NULL DEFAULT ''"),
            ("next_attempt_at", "TEXT NOT NULL DEFAULT ''"),
            ("transport_key", "TEXT NOT NULL DEFAULT ''"),
        ):
            if name not in columns:
                db.execute(f"ALTER TABLE notification_delivery ADD COLUMN {name} {ddl}")
        db.execute("CREATE INDEX IF NOT EXISTS idx_notification_status ON notification_delivery(status, sent_at)")
        db.execute("""CREATE TABLE IF NOT EXISTS notification_transport_health(
          transport_key TEXT PRIMARY KEY,
          consecutive_failures INTEGER NOT NULL DEFAULT 0,
          transient_failures INTEGER NOT NULL DEFAULT 0,
          configuration_failures INTEGER NOT NULL DEFAULT 0,
          circuit_opens INTEGER NOT NULL DEFAULT 0,
          open_until TEXT NOT NULL DEFAULT '',
          last_failure_at TEXT NOT NULL DEFAULT '',
          last_success_at TEXT NOT NULL DEFAULT '',
          last_error TEXT NOT NULL DEFAULT ''
        )""")
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


def _seconds_until(value: str, now: datetime.datetime) -> int:
    if not value:
        return 0
    try:
        target = datetime.datetime.fromisoformat(value)
    except ValueError:
        return 0
    if target.tzinfo is None:
        target = target.replace(tzinfo=datetime.timezone.utc)
    return max(0, int((target.astimezone(datetime.timezone.utc) - now).total_seconds()))


def _public_result(row: sqlite3.Row, *, already_sent: bool = False, in_flight: bool = False, deferred: bool = False, retry_after: int = 0) -> dict:
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
        "deferred": deferred,
        "retryAfterSeconds": int(retry_after or 0),
    }


def _circuit_delay(transport_key: str, now: datetime.datetime) -> int:
    with connect() as db:
        row = db.execute("SELECT open_until FROM notification_transport_health WHERE transport_key=?", (transport_key,)).fetchone()
    return _seconds_until(str(row["open_until"] or ""), now) if row else 0


def _classify_failure(exc: Exception) -> str:
    if isinstance(exc, push_transport.APNSError):
        if exc.token_invalid:
            return "permanent"
        if exc.provider_error:
            return "configuration"
        if exc.retryable:
            return "transient"
    text = str(exc).lower()
    if isinstance(exc, ValueError) or "non configur" in text or "aucun transport" in text:
        return "configuration"
    return "transient"


def _record_transport_failure(transport_key: str, failure_class: str, exc: Exception, now: datetime.datetime, attempt: int) -> tuple[str, int]:
    now_iso = now.isoformat(timespec="seconds")
    retry_after = getattr(exc, "retry_after", "")
    delay = resilience.backoff_seconds(transport_key, attempt, retry_after=retry_after, now=now) if failure_class == "transient" else 0
    if failure_class == "configuration":
        delay = resilience.CONFIGURATION_CIRCUIT_SECONDS
    next_at = (now + datetime.timedelta(seconds=delay)).isoformat(timespec="seconds") if delay else ""
    with connect() as db:
        row = db.execute("SELECT * FROM notification_transport_health WHERE transport_key=?", (transport_key,)).fetchone()
        consecutive = int(row["consecutive_failures"]) + 1 if row else 1
        transient_total = int(row["transient_failures"]) + (1 if failure_class == "transient" else 0) if row else (1 if failure_class == "transient" else 0)
        config_total = int(row["configuration_failures"]) + (1 if failure_class == "configuration" else 0) if row else (1 if failure_class == "configuration" else 0)
        opens = int(row["circuit_opens"]) if row else 0
        should_open = failure_class == "configuration" or (failure_class == "transient" and consecutive >= resilience.CIRCUIT_THRESHOLD)
        open_until = next_at if should_open else ""
        if should_open and (not row or _seconds_until(str(row["open_until"] or ""), now) == 0):
            opens += 1
        db.execute("""INSERT INTO notification_transport_health(
          transport_key,consecutive_failures,transient_failures,configuration_failures,circuit_opens,open_until,last_failure_at,last_error
          ) VALUES(?,?,?,?,?,?,?,?)
          ON CONFLICT(transport_key) DO UPDATE SET consecutive_failures=excluded.consecutive_failures,
          transient_failures=excluded.transient_failures,configuration_failures=excluded.configuration_failures,
          circuit_opens=excluded.circuit_opens,open_until=excluded.open_until,last_failure_at=excluded.last_failure_at,last_error=excluded.last_error""",
          (transport_key, consecutive, transient_total, config_total, opens, open_until, now_iso, _safe_error(exc)))
    return next_at, delay


def _record_transport_success(transport_key: str) -> None:
    now = _now_iso()
    with connect() as db:
        db.execute("""INSERT INTO notification_transport_health(transport_key,last_success_at) VALUES(?,?)
          ON CONFLICT(transport_key) DO UPDATE SET consecutive_failures=0,open_until='',last_success_at=excluded.last_success_at,last_error=''""",
          (transport_key, now))



def _deferred_result(channel: str, category: str, reference: str, retry_after: int, row: sqlite3.Row | None = None) -> dict:
    return {
        "ok": False, "channel": channel, "category": category, "reference": reference,
        "status": "deferred", "attempts": int(row["attempts"]) if row else 0,
        "sentAt": str(row["sent_at"] or "") if row else "",
        "alreadySent": False, "inFlight": False, "deferred": True,
        "retryAfterSeconds": max(1, int(retry_after)),
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
    transport_key = f"email:{email_transport.active_transport() or 'unconfigured'}"
    now = _now(); now_iso = now.isoformat(timespec="seconds")
    init_db()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM notification_delivery WHERE idempotency_key=?", (key,)).fetchone()
        if row and row["status"] == "sent":
            return _public_result(row, already_sent=True)
        if row and _lease_active(row, now):
            return _public_result(row, in_flight=True)
        row_delay = _seconds_until(str(row["next_attempt_at"] or ""), now) if row else 0
        if row_delay:
            return _deferred_result("email", category, reference, row_delay, row)
        circuit_delay = _circuit_delay(transport_key, now)
        if circuit_delay:
            return _deferred_result("email", category, reference, circuit_delay, row)
        if row is None:
            db.execute("""INSERT INTO notification_delivery(
              idempotency_key,channel,category,reference,recipient_hash,status,attempts,created_at,last_attempt_at,transport_key
              ) VALUES(?,?,?,?,?,'delivering',1,?,?,?)""",
              (key, "email", category, reference, _recipient_hash(recipient), now_iso, now_iso, transport_key))
            attempt = 1
        else:
            attempt = int(row["attempts"]) + 1
            db.execute("""UPDATE notification_delivery SET status='delivering',attempts=?,last_attempt_at=?,last_error='',
              failure_class='',next_attempt_at='',transport_key=? WHERE idempotency_key=?""",
              (attempt, now_iso, transport_key, key))
    try:
        email_transport.send_email(recipient, subject, text, html)
    except Exception as exc:
        failure_class = _classify_failure(exc)
        next_at, _ = _record_transport_failure(transport_key, failure_class, exc, now, attempt)
        with connect() as db:
            db.execute("""UPDATE notification_delivery SET status='failed',last_error=?,failure_class=?,next_attempt_at=?
              WHERE idempotency_key=?""", (_safe_error(exc), failure_class, next_at, key))
        raise
    _record_transport_success(transport_key)
    sent_at = _now_iso()
    with connect() as db:
        db.execute("""UPDATE notification_delivery SET status='sent',sent_at=?,last_error='',failure_class='',next_attempt_at=''
          WHERE idempotency_key=?""", (sent_at, key))
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
    environment: str = "sandbox",
) -> dict:
    token = str(device_token or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{32,400}", token) or len(token) % 2:
        raise ValueError("Jeton APNs invalide")
    environment = str(environment or "sandbox").strip().lower()
    if environment not in {"sandbox", "production"}:
        raise ValueError("Environnement APNs invalide")
    category = _text(category, "Catégorie", 80)
    reference = _text(reference, "Référence", 160)
    recipient_key = f"{environment}:{token}"
    transport_key = f"push:apns:{environment}"
    key = _delivery_key("push", category, reference, recipient_key)
    now = _now(); now_iso = now.isoformat(timespec="seconds")
    init_db()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM notification_delivery WHERE idempotency_key=?", (key,)).fetchone()
        if row and row["status"] == "sent":
            return _public_result(row, already_sent=True)
        if row and _lease_active(row, now):
            return _public_result(row, in_flight=True)
        row_delay = _seconds_until(str(row["next_attempt_at"] or ""), now) if row else 0
        if row_delay:
            return _deferred_result("push", category, reference, row_delay, row)
        circuit_delay = _circuit_delay(transport_key, now)
        if circuit_delay:
            return _deferred_result("push", category, reference, circuit_delay, row)
        if row is None:
            db.execute("""INSERT INTO notification_delivery(
              idempotency_key,channel,category,reference,recipient_hash,status,attempts,created_at,last_attempt_at,transport_key
              ) VALUES(?,?,?,?,?,'delivering',1,?,?,?)""",
              (key, "push", category, reference, _recipient_hash(recipient_key), now_iso, now_iso, transport_key))
            attempt = 1
        else:
            attempt = int(row["attempts"]) + 1
            db.execute("""UPDATE notification_delivery SET status='delivering',attempts=?,last_attempt_at=?,last_error='',
              failure_class='',next_attempt_at='',transport_key=? WHERE idempotency_key=?""",
              (attempt, now_iso, transport_key, key))
    try:
        push_transport.send(token, title, body, data=data, environment=environment)
    except Exception as exc:
        failure_class = _classify_failure(exc)
        next_at, _ = _record_transport_failure(transport_key, failure_class, exc, now, attempt)
        with connect() as db:
            db.execute("""UPDATE notification_delivery SET status='failed',last_error=?,failure_class=?,next_attempt_at=?
              WHERE idempotency_key=?""", (_safe_error(exc), failure_class, next_at, key))
        raise
    _record_transport_success(transport_key)
    sent_at = _now_iso()
    with connect() as db:
        db.execute("""UPDATE notification_delivery SET status='sent',sent_at=?,last_error='',failure_class='',next_attempt_at=''
          WHERE idempotency_key=?""", (sent_at, key))
        row = db.execute("SELECT * FROM notification_delivery WHERE idempotency_key=?", (key,)).fetchone()
    return _public_result(row)

def status(limit: int = 20) -> dict:
    init_db()
    limit = max(1, min(int(limit), 100))
    now = _now()
    with connect() as db:
        counts = {
            row["status"]: int(row["n"])
            for row in db.execute("SELECT status,COUNT(*) n FROM notification_delivery GROUP BY status")
        }
        counts["deferred"] = int(db.execute(
            "SELECT COUNT(*) n FROM notification_delivery WHERE status='failed' AND next_attempt_at>?",
            (now.isoformat(timespec="seconds"),),
        ).fetchone()["n"])
        failure_counts = {
            row["failure_class"]: int(row["n"])
            for row in db.execute("SELECT failure_class,COUNT(*) n FROM notification_delivery WHERE failure_class<>'' GROUP BY failure_class")
        }
        recent = [dict(row) for row in db.execute(
            """SELECT channel,category,reference,status,attempts,created_at,last_attempt_at,sent_at,last_error,failure_class,next_attempt_at
               FROM notification_delivery ORDER BY COALESCE(sent_at,last_attempt_at,created_at) DESC LIMIT ?""", (limit,))]
        health_rows = [dict(row) for row in db.execute(
            "SELECT * FROM notification_transport_health ORDER BY transport_key")]
    transports = []
    for item in health_rows:
        retry = _seconds_until(str(item.get("open_until") or ""), now)
        transports.append({
            "transport": item["transport_key"],
            "circuitOpen": retry > 0,
            "retryAfterSeconds": retry,
            "consecutiveFailures": int(item["consecutive_failures"]),
            "transientFailures": int(item["transient_failures"]),
            "configurationFailures": int(item["configuration_failures"]),
            "circuitOpens": int(item["circuit_opens"]),
            "lastFailureAt": item["last_failure_at"],
            "lastSuccessAt": item["last_success_at"],
        })
    return {
        "ok": True,
        "channels": {"email": email_transport.transport_status(), "push": push_transport.status()},
        "counts": counts,
        "failureCounts": failure_counts,
        "resilience": {
            "circuitThreshold": resilience.CIRCUIT_THRESHOLD,
            "baseBackoffSeconds": resilience.BASE_BACKOFF_SECONDS,
            "maxBackoffSeconds": resilience.MAX_BACKOFF_SECONDS,
            "circuitsOpen": sum(1 for item in transports if item["circuitOpen"]),
            "transports": transports,
        },
        "recent": recent,
        "privacy": "Les destinataires et le contenu des notifications ne sont pas persistés par le broker.",
    }
