from __future__ import annotations

import datetime
import hashlib
import json
import os
import sqlite3
import threading
from pathlib import Path
from zoneinfo import ZoneInfo

import email_gateway as mail
import mercure_admin_client as mercure
import notification_broker as notifications
import reminder_engine as reminders

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("CYBERCHECK_DATA_DIR", "/root/CyberCheckData"))
DB = DATA_DIR / "reminder-dispatch.sqlite3"
RECENT_DAYS = 14
BACKFILL_DAYS = 730
BACKFILL_CHUNK_DAYS = 31
INTERVAL_SECONDS = 3600
_STOP = threading.Event()
_THREAD = None

def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _now_iso() -> str:
    return _now().isoformat(timespec="seconds")


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
        db.execute("""CREATE TABLE IF NOT EXISTS reminder_target(
          vehicle_id TEXT PRIMARY KEY,
          client_kind TEXT NOT NULL,
          client_id TEXT NOT NULL,
          due_date TEXT NOT NULL,
          appointment_id TEXT NOT NULL DEFAULT '',
          first_seen_at TEXT NOT NULL,
          last_seen_at TEXT NOT NULL
        )""")
        db.execute("CREATE INDEX IF NOT EXISTS idx_reminder_due ON reminder_target(due_date)")
        db.execute("""CREATE TABLE IF NOT EXISTS reminder_meta(
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )""")
    try:
        DB.chmod(0o600)
    except PermissionError:
        pass


def _meta(key: str, default: str = "") -> str:
    init_db()
    with connect() as db:
        row = db.execute("SELECT value FROM reminder_meta WHERE key=?", (key,)).fetchone()
    return str(row["value"]) if row else default


def _set_meta(key: str, value: str) -> None:
    init_db()
    with connect() as db:
        db.execute(
            """INSERT INTO reminder_meta(key,value,updated_at) VALUES(?,?,?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at""",
            (key, str(value), _now_iso()),
        )


def _upsert(rows: list[dict]) -> int:
    if not rows:
        return 0
    now = _now_iso()
    with connect() as db:
        for row in rows:
            db.execute(
                """INSERT INTO reminder_target(vehicle_id,client_kind,client_id,due_date,appointment_id,first_seen_at,last_seen_at)
                   VALUES(?,?,?,?,?,?,?)
                   ON CONFLICT(vehicle_id) DO UPDATE SET
                   client_kind=excluded.client_kind,client_id=excluded.client_id,due_date=excluded.due_date,
                   appointment_id=excluded.appointment_id,last_seen_at=excluded.last_seen_at""",
                (row["vehicleId"], row["clientKind"], row["clientId"], row["dueDate"], row.get("appointmentId", ""), now, now),
            )
    return len(rows)

def _vehicle_id(value: object) -> str:
    raw = str(value or "").strip()
    if not raw or len(raw) > 128 or any(ch.isspace() for ch in raw):
        raise ValueError("vehicleId invalide")
    return raw


def mobile_claim_target(vehicle_id: object) -> dict:
    """Return the authoritative reminder tuple used to issue a mobile claim.

    Client identifiers never come from the admin request; they are resolved from the
    already-synchronized Mercure reminder inventory.
    """
    clean = _vehicle_id(vehicle_id)
    init_db()
    with connect() as db:
        row = db.execute(
            """SELECT vehicle_id,client_kind,client_id,due_date,appointment_id,last_seen_at
               FROM reminder_target WHERE vehicle_id=?""",
            (clean,),
        ).fetchone()
    if not row:
        raise LookupError("véhicule absent de l inventaire Mercure")
    return dict(row)


def mobile_claim_candidates(limit: int = 30) -> list[dict]:
    limit = max(1, min(int(limit), 100))
    today = _local_now().date().isoformat()
    init_db()
    with connect() as db:
        rows = db.execute(
            """SELECT vehicle_id,due_date,appointment_id,last_seen_at
               FROM reminder_target WHERE due_date>=?
               ORDER BY last_seen_at DESC, due_date ASC, vehicle_id ASC LIMIT ?""",
            (today, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def deadlines_for_vehicle_ids(vehicle_ids: list[str]) -> list[dict]:
    if not isinstance(vehicle_ids, list) or len(vehicle_ids) > 1000:
        raise ValueError("vehicle_ids invalides")
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in vehicle_ids:
        raw = str(value or "").strip()
        if not raw or len(raw) > 128:
            raise ValueError("vehicle_id invalide")
        if raw not in seen:
            seen.add(raw)
            cleaned.append(raw)
    if not cleaned:
        return []
    init_db()
    placeholders = ",".join("?" for _ in cleaned)
    with connect() as db:
        rows = db.execute(
            f"""SELECT vehicle_id,due_date FROM reminder_target
                WHERE vehicle_id IN ({placeholders})""",
            tuple(cleaned),
        )
        return [dict(row) for row in rows]


def sync_once(today: datetime.date | None = None) -> dict:
    init_db()
    today = today or datetime.date.today()
    session = mercure.session_status()
    if not session.get("connected"):
        return {"ok": False, "state": "waiting_mercure", "error": session.get("error", "Session Mercure indisponible")}

    recent_start = today - datetime.timedelta(days=RECENT_DAYS)
    recent_end = today + datetime.timedelta(days=1)
    recent = mercure.reminder_source_rows(recent_start.isoformat(), recent_end.isoformat())
    touched = _upsert(recent)

    floor = today - datetime.timedelta(days=BACKFILL_DAYS)
    cursor_raw = _meta("backfill_cursor_end", (today - datetime.timedelta(days=RECENT_DAYS)).isoformat())
    try:
        cursor_end = datetime.date.fromisoformat(cursor_raw)
    except ValueError:
        cursor_end = today - datetime.timedelta(days=RECENT_DAYS)
    backfill_rows = []
    if cursor_end > floor:
        chunk_start = max(floor, cursor_end - datetime.timedelta(days=BACKFILL_CHUNK_DAYS))
        backfill_rows = mercure.reminder_source_rows(chunk_start.isoformat(), cursor_end.isoformat())
        touched += _upsert(backfill_rows)
        cursor_end = chunk_start
        _set_meta("backfill_cursor_end", cursor_end.isoformat())
    complete = cursor_end <= floor
    result = {
        "ok": True, "state": "synced", "recentRows": len(recent),
        "backfillRows": len(backfill_rows), "touched": touched,
        "backfillCursorEnd": cursor_end.isoformat(), "backfillComplete": complete,
    }
    _set_meta("last_sync", json.dumps(result, separators=(",", ":")))
    return result


def _local_now(now: datetime.datetime | None = None) -> datetime.datetime:
    tz = ZoneInfo(reminders.DEFAULT_TIMEZONE)
    if now is None:
        return datetime.datetime.now(tz)
    if now.tzinfo is None:
        return now.replace(tzinfo=tz)
    return now.astimezone(tz)


def _eligible(now: datetime.datetime | None = None) -> list[dict]:
    local = _local_now(now)
    if local.hour < reminders.DEFAULT_HOUR:
        return []
    today = local.date()
    with connect() as db:
        rows = [dict(row) for row in db.execute(
            "SELECT vehicle_id,client_kind,client_id,due_date,appointment_id FROM reminder_target WHERE due_date>=? AND due_date<=?",
            (today.isoformat(), (today + datetime.timedelta(days=max(reminders.DEFAULT_LEAD_DAYS))).isoformat()),
        )]
    out = []
    for row in rows:
        try:
            due = datetime.date.fromisoformat(row["due_date"])
        except ValueError:
            continue
        lead = (due - today).days
        if lead in reminders.DEFAULT_LEAD_DAYS:
            row["days_before"] = lead
            out.append(row)
    return out

def _booking_url() -> str:
    try:
        data = json.loads((ROOT / "data" / "site-config.json").read_text())
        canonical = str((data.get("seo") or {}).get("canonicalUrl") or "").strip()
        if canonical.startswith("https://"):
            return canonical.rstrip("/") + "/#reservation"
    except Exception:
        pass
    return "https://www.checkupauto.fr/#reservation"


def _message(due_date: str) -> tuple[str, str]:
    due = datetime.date.fromisoformat(due_date)
    due_fr = due.strftime("%d/%m/%Y")
    url = _booking_url()
    subject = f"Contrôle technique : échéance le {due_fr}"
    text = (
        "Bonjour,\n\n"
        f"La date d’échéance enregistrée pour votre véhicule approche : {due_fr}.\n"
        f"Vous pouvez réserver votre contrôle technique chez Checkup Auto : {url}\n\n"
        "Checkup Auto"
    )
    return subject, text


def _reference(row: dict) -> str:
    vehicle_hash = hashlib.sha256(("mercure:" + row["vehicle_id"]).encode()).hexdigest()[:24]
    return f"ct-reminder:{vehicle_hash}:{row['due_date']}:j{row['days_before']}"


def process_once(now: datetime.datetime | None = None, *, do_sync: bool = True) -> dict:
    init_db()
    sync = sync_once(_local_now(now).date()) if do_sync else {"ok": True, "state": "skipped"}
    if not sync.get("ok"):
        result = {"ok": False, "state": sync.get("state", "sync_failed"), "sync": sync}
        _set_meta("last_process", json.dumps(result, separators=(",", ":")))
        return result

    local = _local_now(now)
    eligible = _eligible(local)
    if local.hour < reminders.DEFAULT_HOUR:
        result = {"ok": True, "state": "before_send_window", "eligible": 0, "sync": sync}
        _set_meta("last_process", json.dumps(result, separators=(",", ":")))
        return result
    if not mail.configured():
        result = {"ok": True, "state": "waiting_email_transport", "eligible": len(eligible), "sync": sync}
        _set_meta("last_process", json.dumps(result, separators=(",", ":")))
        return result
    try:
        email_preflight = mail.preflight()
    except Exception:
        result = {
            "ok": False,
            "state": "email_preflight_failed",
            "eligible": len(eligible),
            "preflightState": "unavailable",
            "sync": sync,
        }
        _set_meta("last_process", json.dumps(result, separators=(",", ":")))
        return result
    if not bool(email_preflight.get("ok")):
        result = {
            "ok": True,
            "state": "waiting_email_preflight",
            "eligible": len(eligible),
            "preflightState": str(email_preflight.get("state") or "unknown"),
            "sync": sync,
        }
        _set_meta("last_process", json.dumps(result, separators=(",", ":")))
        return result
    sent = already = deferred = failed = missing = in_flight = 0
    for row in eligible:
        try:
            recipient = mercure.customer_email(row["client_kind"], row["client_id"])
            if not mail.valid_email(recipient):
                missing += 1
                continue
            subject, text = _message(row["due_date"])
            delivery = notifications.send_email(
                recipient, subject, text,
                category="ct_due_reminder", reference=_reference(row),
            )
            if delivery.get("alreadySent"):
                already += 1
            elif delivery.get("inFlight"):
                in_flight += 1
            elif delivery.get("deferred"):
                deferred += 1
            else:
                sent += 1
        except Exception:
            failed += 1
    result = {
        "ok": failed == 0,
        "state": "active" if failed == 0 else "partial_failure",
        "eligible": len(eligible), "sent": sent, "alreadySent": already,
        "inFlight": in_flight, "deferred": deferred, "missingRecipient": missing, "failed": failed,
        "sync": sync,
    }
    _set_meta("last_process", json.dumps(result, separators=(",", ":")))
    return result


def status(now: datetime.datetime | None = None) -> dict:
    init_db(); local = _local_now(now); today = local.date()
    with connect() as db:
        total = int(db.execute("SELECT COUNT(*) n FROM reminder_target").fetchone()["n"])
        future = int(db.execute("SELECT COUNT(*) n FROM reminder_target WHERE due_date>=?", (today.isoformat(),)).fetchone()["n"])
        next_row = db.execute("SELECT due_date FROM reminder_target WHERE due_date>=? ORDER BY due_date LIMIT 1", (today.isoformat(),)).fetchone()
    raw = _meta("last_process", "")
    try:
        last_process = json.loads(raw) if raw else None
    except Exception:
        last_process = None
    cursor_raw = _meta("backfill_cursor_end", "")
    floor = today - datetime.timedelta(days=BACKFILL_DAYS)
    complete = False
    if cursor_raw:
        try: complete = datetime.date.fromisoformat(cursor_raw) <= floor
        except ValueError: pass
    return {
        "ok": True,
        "sessionConnected": bool(mercure.session_status().get("connected")),
        "emailTransportConfigured": mail.configured(),
        "leadDays": list(reminders.DEFAULT_LEAD_DAYS), "sendHour": reminders.DEFAULT_HOUR,
        "timezone": reminders.DEFAULT_TIMEZONE,
        "inventory": total, "futureDueDates": future,
        "nextDueDate": str(next_row["due_date"]) if next_row else "",
        "eligibleNow": len(_eligible(local)),
        "backfillCursorEnd": cursor_raw, "backfillComplete": complete,
        "lastProcess": last_process,
        "privacy": "CyberCheck conserve les identifiants techniques véhicule/client et la date d’échéance, jamais l’adresse email du client.",
    }

def _loop() -> None:
    while not _STOP.is_set():
        try:
            process_once()
        except Exception:
            pass
        if _STOP.wait(INTERVAL_SECONDS):
            break


def start(interval: int = INTERVAL_SECONDS) -> None:
    global _THREAD, INTERVAL_SECONDS
    init_db()
    if interval != INTERVAL_SECONDS:
        INTERVAL_SECONDS = max(300, int(interval))
    if _THREAD and _THREAD.is_alive():
        return
    _STOP.clear()
    _THREAD = threading.Thread(target=_loop, daemon=True, name="CyberCheckReminderDispatch")
    _THREAD.start()


def stop() -> None:
    _STOP.set()
