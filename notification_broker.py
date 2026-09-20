from __future__ import annotations

import datetime, math
import hashlib
import os
import re
import sqlite3
import uuid
from pathlib import Path

import email_gateway as email_transport
import apns_gateway as push_transport
import delivery_resilience as resilience

DATA_DIR = Path(os.environ.get("CYBERCHECK_DATA_DIR", "/root/CyberCheckData"))
DB = DATA_DIR / "notification-broker.sqlite3"
LEASE_SECONDS = 120
MAX_ERROR = 300
RECIPIENT_CHECK_STALE_SECONDS = 7200


class PermanentDeliverySuppressed(RuntimeError):
    pass


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


def _diagnostic_token(value: object, *, limit: int = 80) -> str:
    raw = str(value or "").strip()[:limit]
    return raw if re.fullmatch(r"[A-Za-z0-9_.:-]+", raw) else ""


def safe_delivery_error(exc: Exception) -> str:
    """Return a persistable diagnostic without arbitrary exception text or PII."""
    if isinstance(exc, email_transport.EmailDeliveryError):
        fields = [
            "EmailDeliveryError",
            f"transport={_diagnostic_token(exc.transport, limit=40) or 'email'}",
            f"class={_diagnostic_token(exc.failure_class, limit=24) or 'unknown'}",
        ]
        if int(exc.status or 0):
            fields.append(f"status={int(exc.status)}")
        reason = _diagnostic_token(exc.reason)
        if reason:
            fields.append(f"reason={reason}")
        return " ".join(fields)[:MAX_ERROR]
    if isinstance(exc, push_transport.APNSError):
        fields = ["APNSError", f"status={int(exc.status or 0)}"]
        reason = _diagnostic_token(exc.reason, limit=120)
        if reason:
            fields.append(f"reason={reason}")
        return " ".join(fields)[:MAX_ERROR]
    name = _diagnostic_token(type(exc).__name__, limit=80)
    return (name or "DeliveryError")[:MAX_ERROR]


# Backward-compatible private alias for older internal callers/tests.
_safe_error = safe_delivery_error


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
            ("incident_id", "TEXT NOT NULL DEFAULT ''"),
            ("permanent_state", "TEXT NOT NULL DEFAULT ''"),
            ("permanent_state_at", "TEXT NOT NULL DEFAULT ''"),
            ("permanent_resolution", "TEXT NOT NULL DEFAULT ''"),
            ("recipient_check_state", "TEXT NOT NULL DEFAULT ''"),
            ("recipient_checked_at", "TEXT NOT NULL DEFAULT ''"),
            ("recipient_change_detected_at", "TEXT NOT NULL DEFAULT ''"),
        ):
            if name not in columns:
                db.execute(f"ALTER TABLE notification_delivery ADD COLUMN {name} {ddl}")
        db.execute("""UPDATE notification_delivery
          SET permanent_state='open',
              permanent_state_at=COALESCE(NULLIF(last_attempt_at,''),created_at),
              incident_id=CASE WHEN incident_id='' THEN lower(hex(randomblob(16))) ELSE incident_id END
          WHERE failure_class='permanent' AND permanent_state=''""")
        db.execute("CREATE INDEX IF NOT EXISTS idx_notification_status ON notification_delivery(status, sent_at)")
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_notification_incident ON notification_delivery(incident_id) WHERE incident_id<>''")
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
    return max(0, math.ceil((target.astimezone(datetime.timezone.utc) - now).total_seconds()))


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
    if isinstance(exc, email_transport.EmailDeliveryError):
        return exc.failure_class
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
    next_at = (now + datetime.timedelta(seconds=delay)).isoformat(timespec="microseconds") if delay else ""
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


def _record_delivery_failure(key: str, failure_class: str, diagnostic: str, next_at: str, now_iso: str) -> None:
    with connect() as db:
        if failure_class == "permanent":
            db.execute("""UPDATE notification_delivery
              SET status='failed',last_error=?,failure_class=?,next_attempt_at='',
                  incident_id=CASE WHEN incident_id='' THEN ? ELSE incident_id END,
                  permanent_state='open',permanent_state_at=?,permanent_resolution='',
                  recipient_check_state='',recipient_checked_at='',recipient_change_detected_at=''
              WHERE idempotency_key=?""",
              (diagnostic, failure_class, uuid.uuid4().hex, now_iso, key))
        else:
            db.execute("""UPDATE notification_delivery SET status='failed',last_error=?,failure_class=?,next_attempt_at=?
              WHERE idempotency_key=?""", (diagnostic, failure_class, next_at, key))


def _reconcile_permanent_failures(db: sqlite3.Connection, channel: str, category: str, reference: str, successful_key: str, sent_at: str) -> int:
    result = db.execute("""UPDATE notification_delivery
      SET permanent_state='resolved',permanent_state_at=?,permanent_resolution='superseded_by_success'
      WHERE channel=? AND category=? AND reference=? AND idempotency_key<>?
        AND failure_class='permanent' AND permanent_state IN ('open','acknowledged')""",
      (sent_at, channel, category, reference, successful_key))
    return int(result.rowcount or 0)


def _permanent_failure_row(incident_id: object) -> sqlite3.Row:
    incident = str(incident_id or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{32}", incident):
        raise ValueError("incident_id_invalid")
    init_db()
    with connect() as db:
        row = db.execute("""SELECT incident_id,channel,category,reference,recipient_hash,failure_class,
          permanent_state,permanent_state_at,permanent_resolution,last_attempt_at,last_error,
          recipient_check_state,recipient_checked_at,recipient_change_detected_at
          FROM notification_delivery WHERE incident_id=?""", (incident,)).fetchone()
    if row is None or row["failure_class"] != "permanent":
        raise LookupError("permanent_failure_not_found")
    return row


def permanent_failure_context(incident_id: object) -> dict:
    """Return non-recipient context needed to govern a permanent incident."""
    row = _permanent_failure_row(incident_id)
    return {
        "incidentId": row["incident_id"],
        "channel": row["channel"],
        "category": row["category"],
        "reference": row["reference"],
        "permanentState": row["permanent_state"] or "open",
        "permanentStateAt": row["permanent_state_at"],
        "permanentResolution": row["permanent_resolution"],
        "recipientCheckState": row["recipient_check_state"],
        "recipientCheckedAt": row["recipient_checked_at"],
        "recipientChangeDetectedAt": row["recipient_change_detected_at"],
    }


def record_permanent_recipient_check(incident_id: object, state: object) -> dict:
    """Persist only a bounded recipient reconciliation state, never recipient data."""
    incident = str(incident_id or "").strip().lower()
    recipient_state = str(state or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{32}", incident):
        raise ValueError("incident_id_invalid")
    if recipient_state not in {"changed", "unchanged", "missing", "lookup_failed"}:
        raise ValueError("recipient_check_state_invalid")
    init_db()
    checked_at = _now_iso()
    with connect() as db:
        row = db.execute(
            "SELECT failure_class,recipient_check_state,recipient_change_detected_at FROM notification_delivery WHERE incident_id=?",
            (incident,),
        ).fetchone()
        if row is None or row["failure_class"] != "permanent":
            raise LookupError("permanent_failure_not_found")
        previous = str(row["recipient_check_state"] or "")
        transitioned = recipient_state == "changed" and previous != "changed"
        if recipient_state == "changed":
            change_detected_at = checked_at if transitioned else str(row["recipient_change_detected_at"] or checked_at)
        else:
            change_detected_at = ""
        db.execute(
            """UPDATE notification_delivery
               SET recipient_check_state=?,recipient_checked_at=?,recipient_change_detected_at=?
               WHERE incident_id=?""",
            (recipient_state, checked_at, change_detected_at, incident),
        )
    return {
        "ok": True, "incidentId": incident,
        "recipientState": recipient_state, "recipientCheckedAt": checked_at,
        "transitionedToChanged": transitioned, "recipientChangeDetectedAt": change_detected_at,
    }


def permanent_failure_recipient_state(incident_id: object, recipient: object) -> dict:
    """Compare a current recipient with the failed one without exposing either hash."""
    current = _text(recipient, "Destinataire", 512)
    row = _permanent_failure_row(incident_id)
    state = "unchanged" if _recipient_hash(current) == row["recipient_hash"] else "changed"
    persisted = record_permanent_recipient_check(row["incident_id"], state)
    return {
        "ok": True,
        "incidentId": row["incident_id"],
        "recipientState": state,
        "recipientCheckedAt": persisted["recipientCheckedAt"],
        "transitionedToChanged": bool(persisted.get("transitionedToChanged")),
        "recipientChangeDetectedAt": persisted.get("recipientChangeDetectedAt", ""),
        "permanentState": row["permanent_state"] or "open",
    }


def permanent_failure_action(incident_id: object, action: object) -> dict:
    incident = str(incident_id or "").strip().lower()
    requested = str(action or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{32}", incident):
        raise ValueError("incident_id_invalid")
    if requested not in {"acknowledge", "reopen"}:
        raise ValueError("action_invalid")
    init_db()
    now = _now_iso()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("""SELECT incident_id,channel,category,reference,last_attempt_at,last_error,
          failure_class,permanent_state,permanent_state_at,permanent_resolution
          FROM notification_delivery WHERE incident_id=?""", (incident,)).fetchone()
        if row is None or row["failure_class"] != "permanent":
            raise LookupError("permanent_failure_not_found")
        current = str(row["permanent_state"] or "open")
        if requested == "acknowledge":
            if current == "resolved":
                raise ValueError("resolved_failure_is_immutable")
            target = "acknowledged"
        else:
            if current == "resolved":
                raise ValueError("resolved_failure_is_immutable")
            target = "open"
        db.execute("""UPDATE notification_delivery SET permanent_state=?,permanent_state_at=?
          WHERE incident_id=?""", (target, now, incident))
        row = db.execute("""SELECT incident_id,channel,category,reference,last_attempt_at,last_error,
          permanent_state,permanent_state_at,permanent_resolution
          FROM notification_delivery WHERE incident_id=?""", (incident,)).fetchone()
    return {
        "ok": True,
        "incidentId": row["incident_id"],
        "channel": row["channel"],
        "category": row["category"],
        "reference": row["reference"],
        "lastAttemptAt": row["last_attempt_at"],
        "diagnostic": row["last_error"],
        "permanentState": row["permanent_state"],
        "permanentStateAt": row["permanent_state_at"],
        "permanentResolution": row["permanent_resolution"],
    }



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
        if row and row["failure_class"] == "permanent":
            raise PermanentDeliverySuppressed("Échec permanent déjà enregistré pour cette livraison")
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
        _record_delivery_failure(key, failure_class, _safe_error(exc), next_at, now_iso)
        raise
    _record_transport_success(transport_key)
    sent_at = _now_iso()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("""UPDATE notification_delivery SET status='sent',sent_at=?,last_error='',failure_class='',next_attempt_at='',
          permanent_state='',permanent_state_at='',permanent_resolution='' WHERE idempotency_key=?""", (sent_at, key))
        _reconcile_permanent_failures(db, "email", category, reference, key, sent_at)
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
    notification_category: str = "",
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
        if row and row["failure_class"] == "permanent":
            raise PermanentDeliverySuppressed("Échec permanent déjà enregistré pour cette livraison")
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
        push_transport.send(
            token,
            title,
            body,
            data=data,
            environment=environment,
            notification_category=notification_category,
        )
    except Exception as exc:
        failure_class = _classify_failure(exc)
        next_at, _ = _record_transport_failure(transport_key, failure_class, exc, now, attempt)
        _record_delivery_failure(key, failure_class, _safe_error(exc), next_at, now_iso)
        raise
    _record_transport_success(transport_key)
    sent_at = _now_iso()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("""UPDATE notification_delivery SET status='sent',sent_at=?,last_error='',failure_class='',next_attempt_at='',
          permanent_state='',permanent_state_at='',permanent_resolution='' WHERE idempotency_key=?""", (sent_at, key))
        _reconcile_permanent_failures(db, "push", category, reference, key, sent_at)
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
        permanent_counts = {
            row["permanent_state"]: int(row["n"])
            for row in db.execute("""SELECT permanent_state,COUNT(*) n FROM notification_delivery
              WHERE failure_class='permanent' GROUP BY permanent_state""")
        }
        recent = [dict(row) for row in db.execute(
            """SELECT channel,category,reference,status,attempts,created_at,last_attempt_at,sent_at,last_error,failure_class,next_attempt_at,
                      permanent_state,permanent_state_at,permanent_resolution,recipient_check_state,recipient_checked_at,recipient_change_detected_at
               FROM notification_delivery ORDER BY COALESCE(sent_at,last_attempt_at,created_at) DESC LIMIT ?""", (limit,))]
        permanent_rows = [dict(row) for row in db.execute(
            """SELECT incident_id,channel,category,reference,last_attempt_at,last_error,permanent_state,permanent_state_at,permanent_resolution,
                      recipient_check_state,recipient_checked_at,recipient_change_detected_at
               FROM notification_delivery WHERE failure_class='permanent'
               ORDER BY COALESCE(permanent_state_at,last_attempt_at,created_at) DESC LIMIT ?""", (limit,))]
        recipient_rows = [dict(row) for row in db.execute(
            """SELECT recipient_check_state,recipient_checked_at,recipient_change_detected_at
               FROM notification_delivery
               WHERE failure_class='permanent' AND permanent_state IN ('open','acknowledged')
                 AND channel='email' AND category='ct_due_reminder'""")]
        health_rows = [dict(row) for row in db.execute(
            "SELECT * FROM notification_transport_health ORDER BY transport_key")]
    recipient_checks = {
        "tracked": len(recipient_rows), "fresh": 0, "stale": 0, "unchecked": 0,
        "changed": 0, "unchanged": 0, "missing": 0, "lookupFailed": 0,
        "staleAfterSeconds": RECIPIENT_CHECK_STALE_SECONDS,
    }
    for item in recipient_rows:
        state = str(item.get("recipient_check_state") or "")
        if state == "changed":
            recipient_checks["changed"] += 1
        elif state == "unchanged":
            recipient_checks["unchanged"] += 1
        elif state == "missing":
            recipient_checks["missing"] += 1
        elif state == "lookup_failed":
            recipient_checks["lookupFailed"] += 1
        checked_at = str(item.get("recipient_checked_at") or "")
        if not checked_at:
            recipient_checks["unchecked"] += 1
            recipient_checks["stale"] += 1
            continue
        try:
            checked = datetime.datetime.fromisoformat(checked_at)
            if checked.tzinfo is None:
                checked = checked.replace(tzinfo=datetime.timezone.utc)
            age = max(0.0, (now - checked.astimezone(datetime.timezone.utc)).total_seconds())
        except (TypeError, ValueError):
            recipient_checks["stale"] += 1
            continue
        if age <= RECIPIENT_CHECK_STALE_SECONDS:
            recipient_checks["fresh"] += 1
        else:
            recipient_checks["stale"] += 1
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
            "permanentFailures": int(permanent_counts.get("open", 0)),
            "permanentFailureHistory": int(failure_counts.get("permanent", 0)),
            "permanentAcknowledged": int(permanent_counts.get("acknowledged", 0)),
            "permanentResolved": int(permanent_counts.get("resolved", 0)),
            "recipientChecks": recipient_checks,
            "transports": transports,
        },
        "permanentFailures": permanent_rows,
        "recent": recent,
        "privacy": "Les destinataires et le contenu des notifications ne sont pas persistés par le broker.",
    }
