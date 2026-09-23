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
import privacy_suppression as privacy

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
          last_seen_at TEXT NOT NULL,
          source_window_end TEXT NOT NULL DEFAULT '',
          quarantined INTEGER NOT NULL DEFAULT 0
        )""")
        columns = {str(row["name"]) for row in db.execute("PRAGMA table_info(reminder_target)")}
        if "source_window_end" not in columns:
            db.execute("ALTER TABLE reminder_target ADD COLUMN source_window_end TEXT NOT NULL DEFAULT ''")
        if "quarantined" not in columns:
            db.execute("ALTER TABLE reminder_target ADD COLUMN quarantined INTEGER NOT NULL DEFAULT 0")
        db.execute("CREATE INDEX IF NOT EXISTS idx_reminder_due ON reminder_target(due_date)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_reminder_quarantined ON reminder_target(quarantined,due_date)")
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


def _source_window_end(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        return datetime.date.fromisoformat(raw).isoformat()
    except ValueError as exc:
        raise ValueError("source_window_end invalide") from exc


def _upsert(rows: list[dict], source_window_end: object = "") -> int:
    """Merge one Mercure observation window without letting older history win.

    The backfill walks backwards in time.  ``source_window_end`` therefore acts as a
    monotonic recency marker: an older backfill window may populate a missing vehicle,
    but it cannot replace a client identity observed in a newer window.  When the same
    window associates one vehicle with multiple client identities, the vehicle is
    quarantined instead of choosing a recipient from provider ordering.
    """
    if not rows:
        return 0
    observed_through = _source_window_end(source_window_end)
    now = _now_iso()
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        vehicle_id = str(row.get("vehicleId") or "").strip()
        if not vehicle_id or len(vehicle_id) > 128 or any(ch.isspace() for ch in vehicle_id):
            raise ValueError("vehicleId invalide")
        client_kind = str(row.get("clientKind") or "").strip()
        client_id = str(row.get("clientId") or "").strip()
        candidates=[("vehicle",vehicle_id)]
        if client_kind in {"account","free"} and client_id:
            candidates.append(("mercure_"+client_kind,client_id))
        if privacy.any_suppressed(candidates,"all_processing"):
            continue
        grouped.setdefault(vehicle_id, []).append(row)

    applied = 0
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        for vehicle_id, candidates in grouped.items():
            identities = {
                (str(row.get("clientKind") or "").strip(), str(row.get("clientId") or "").strip())
                for row in candidates
            }
            representative = candidates[0]
            if len(identities) != 1:
                existing = db.execute(
                    "SELECT source_window_end FROM reminder_target WHERE vehicle_id=?",
                    (vehicle_id,),
                ).fetchone()
                if existing:
                    cursor = db.execute(
                        """UPDATE reminder_target
                           SET quarantined=1,source_window_end=?,last_seen_at=?
                           WHERE vehicle_id=? AND (
                             source_window_end='' OR (?<>'' AND ?>=source_window_end)
                           )""",
                        (observed_through, now, vehicle_id, observed_through, observed_through),
                    )
                    applied += max(0, int(cursor.rowcount or 0))
                else:
                    db.execute(
                        """INSERT INTO reminder_target(
                             vehicle_id,client_kind,client_id,due_date,appointment_id,
                             first_seen_at,last_seen_at,source_window_end,quarantined
                           ) VALUES(?,?,?,?,?,?,?,?,1)""",
                        (
                            vehicle_id,
                            str(representative.get("clientKind") or ""),
                            str(representative.get("clientId") or ""),
                            str(representative.get("dueDate") or ""),
                            str(representative.get("appointmentId") or ""),
                            now,
                            now,
                            observed_through,
                        ),
                    )
                    applied += 1
                continue

            row = representative
            cursor = db.execute(
                """INSERT INTO reminder_target(
                     vehicle_id,client_kind,client_id,due_date,appointment_id,
                     first_seen_at,last_seen_at,source_window_end,quarantined
                   ) VALUES(?,?,?,?,?,?,?,?,0)
                   ON CONFLICT(vehicle_id) DO UPDATE SET
                     client_kind=excluded.client_kind,
                     client_id=excluded.client_id,
                     due_date=excluded.due_date,
                     appointment_id=excluded.appointment_id,
                     last_seen_at=excluded.last_seen_at,
                     source_window_end=excluded.source_window_end,
                     quarantined=0
                   WHERE reminder_target.source_window_end=''
                      OR (excluded.source_window_end<>'' AND excluded.source_window_end>=reminder_target.source_window_end)""",
                (
                    vehicle_id,
                    str(row.get("clientKind") or ""),
                    str(row.get("clientId") or ""),
                    str(row.get("dueDate") or ""),
                    str(row.get("appointmentId") or ""),
                    now,
                    now,
                    observed_through,
                ),
            )
            applied += max(0, int(cursor.rowcount or 0))
    return applied


def _quarantined_count() -> int:
    init_db()
    with connect() as db:
        return int(db.execute("SELECT COUNT(*) n FROM reminder_target WHERE quarantined=1").fetchone()["n"])


def _vehicle_id(value: object) -> str:
    raw = str(value or "").strip()
    if not raw or len(raw) > 128 or any(ch.isspace() for ch in raw):
        raise ValueError("vehicleId invalide")
    return raw


def _processing_candidates(row: dict) -> list[tuple[str, object]]:
    candidates: list[tuple[str, object]] = [("vehicle", row.get("vehicle_id"))]
    client_kind = str(row.get("client_kind") or "").strip()
    client_id = str(row.get("client_id") or "").strip()
    if client_kind in {"account", "free"} and client_id:
        candidates.append(("mercure_" + client_kind, client_id))
    return candidates


def _all_processing_suppressed(row: dict) -> bool:
    """Re-check current DSAR restriction/erasure state for cached Mercure rows.

    ``reminder_target`` is a cache. A subject can become restricted after a row was
    cached, so import-time checks alone are insufficient. This gate is deliberately
    evaluated before any later provider lookup that could itself constitute processing.
    """
    return privacy.any_suppressed(_processing_candidates(row), "all_processing")


def mobile_claim_target(vehicle_id: object) -> dict:
    """Return the authoritative reminder tuple used to issue a mobile claim.

    Client identifiers never come from the admin request; they are resolved from the
    already-synchronized Mercure reminder inventory. Current all-processing suppression
    is enforced here so direct callers cannot bypass higher-level mobile gates.
    """
    clean = _vehicle_id(vehicle_id)
    init_db()
    with connect() as db:
        row = db.execute(
            """SELECT vehicle_id,client_kind,client_id,due_date,appointment_id,last_seen_at
               FROM reminder_target WHERE vehicle_id=? AND quarantined=0""",
            (clean,),
        ).fetchone()
    if not row:
        raise LookupError("véhicule absent de l inventaire Mercure")
    target = dict(row)
    if _all_processing_suppressed(target):
        raise LookupError("véhicule absent de l inventaire Mercure")
    return target


def mobile_claim_candidates(limit: int = 30) -> list[dict]:
    limit = max(1, min(int(limit), 100))
    today = _local_now().date().isoformat()
    init_db()
    with connect() as db:
        rows = db.execute(
            """SELECT vehicle_id,client_kind,client_id,due_date,appointment_id,last_seen_at
               FROM reminder_target WHERE due_date>=? AND quarantined=0
               ORDER BY last_seen_at DESC, due_date ASC, vehicle_id ASC LIMIT ?""",
            (today, limit),
        ).fetchall()
    visible = []
    for row in rows:
        target = dict(row)
        if _all_processing_suppressed(target):
            continue
        visible.append(
            {
                "vehicle_id": target["vehicle_id"],
                "due_date": target["due_date"],
                "appointment_id": target["appointment_id"],
                "last_seen_at": target["last_seen_at"],
            }
        )
    return visible


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
            f"""SELECT vehicle_id,client_kind,client_id,due_date FROM reminder_target
                WHERE vehicle_id IN ({placeholders}) AND quarantined=0""",
            tuple(cleaned),
        ).fetchall()
    visible = []
    for row in rows:
        target = dict(row)
        if _all_processing_suppressed(target):
            continue
        visible.append({"vehicle_id": target["vehicle_id"], "due_date": target["due_date"]})
    return visible


def sync_once(today: datetime.date | None = None) -> dict:
    init_db()
    today = today or mercure.business_today()
    session = mercure.session_status()
    if not session.get("connected"):
        return {"ok": False, "state": "waiting_mercure", "error": session.get("error", "Session Mercure indisponible")}

    recent_start = today - datetime.timedelta(days=RECENT_DAYS)
    recent_end = today + datetime.timedelta(days=1)
    recent = mercure.reminder_source_rows(recent_start.isoformat(), recent_end.isoformat())
    touched = _upsert(recent, recent_end.isoformat())

    floor = today - datetime.timedelta(days=BACKFILL_DAYS)
    cursor_raw = _meta("backfill_cursor_end", (today - datetime.timedelta(days=RECENT_DAYS)).isoformat())
    try:
        cursor_end = datetime.date.fromisoformat(cursor_raw)
    except ValueError:
        cursor_end = today - datetime.timedelta(days=RECENT_DAYS)
    backfill_rows = []
    if cursor_end > floor:
        chunk_end = cursor_end
        chunk_start = max(floor, chunk_end - datetime.timedelta(days=BACKFILL_CHUNK_DAYS))
        backfill_rows = mercure.reminder_source_rows(chunk_start.isoformat(), chunk_end.isoformat())
        touched += _upsert(backfill_rows, chunk_end.isoformat())
        cursor_end = chunk_start
        _set_meta("backfill_cursor_end", cursor_end.isoformat())
    complete = cursor_end <= floor
    result = {
        "ok": True,
        "state": "synced",
        "recentRows": len(recent),
        "backfillRows": len(backfill_rows),
        "touched": touched,
        "quarantinedTargets": _quarantined_count(),
        "backfillCursorEnd": cursor_end.isoformat(),
        "backfillComplete": complete,
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
            """SELECT vehicle_id,client_kind,client_id,due_date,appointment_id
               FROM reminder_target
               WHERE due_date>=? AND due_date<=? AND quarantined=0""",
            (today.isoformat(), (today + datetime.timedelta(days=max(reminders.DEFAULT_LEAD_DAYS))).isoformat()),
        )]
    out = []
    for row in rows:
        if _all_processing_suppressed(row):
            continue
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


def _target_for_reference(reference: object) -> dict | None:
    ref = str(reference or "").strip()
    if not ref:
        return None
    init_db()
    with connect() as db:
        rows = [dict(row) for row in db.execute(
            """SELECT vehicle_id,client_kind,client_id,due_date,appointment_id
               FROM reminder_target WHERE quarantined=0"""
        )]
    for row in rows:
        if _all_processing_suppressed(row):
            continue
        for days_before in reminders.DEFAULT_LEAD_DAYS:
            candidate = {**row, "days_before": int(days_before)}
            if _reference(candidate) == ref:
                return candidate
    return None


def _permanent_email_target(incident_id: object) -> tuple[dict, dict]:
    context = notifications.permanent_failure_context(incident_id)
    if context.get("channel") != "email" or context.get("category") != "ct_due_reminder":
        raise ValueError("permanent_incident_not_reminder_email")
    if context.get("permanentState") == "resolved":
        raise ValueError("permanent_incident_already_resolved")
    target = _target_for_reference(context.get("reference"))
    if target is None:
        raise LookupError("reminder_reference_not_found")
    return context, target


def permanent_recipient_check(incident_id: object) -> dict:
    """Compare the current Mercure recipient with a permanent failure, without disclosing PII."""
    context, target = _permanent_email_target(incident_id)
    try:
        recipient = mercure.customer_email(target["client_kind"], target["client_id"])
    except Exception:
        persisted = notifications.record_permanent_recipient_check(context["incidentId"], "lookup_failed")
        return {
            "ok": False,
            "incidentId": context["incidentId"],
            "recipientState": "lookup_failed",
            "recipientCheckedAt": persisted["recipientCheckedAt"],
            "retryEligible": False,
        }
    if not mail.valid_email(recipient):
        persisted = notifications.record_permanent_recipient_check(context["incidentId"], "missing")
        return {
            "ok": True,
            "incidentId": context["incidentId"],
            "recipientState": "missing",
            "recipientCheckedAt": persisted["recipientCheckedAt"],
            "retryEligible": False,
        }
    comparison = notifications.permanent_failure_recipient_state(context["incidentId"], recipient)
    changed = comparison.get("recipientState") == "changed"
    return {
        "ok": True,
        "incidentId": context["incidentId"],
        "recipientState": comparison.get("recipientState", "unknown"),
        "recipientCheckedAt": comparison.get("recipientCheckedAt", ""),
        "transitionedToChanged": bool(comparison.get("transitionedToChanged")),
        "recipientChangeDetectedAt": comparison.get("recipientChangeDetectedAt", ""),
        "retryEligible": changed,
    }


def refresh_permanent_recipient_checks(limit: int = 100) -> dict:
    """Refresh unresolved CT reminder recipient state without attempting delivery."""
    limit = max(1, min(int(limit), 250))
    failures = notifications.status(limit=limit).get("permanentFailures") or []
    counts = {"changed": 0, "unchanged": 0, "missing": 0, "lookup_failed": 0, "newlyChanged": 0, "skipped": 0}
    checked = 0
    for item in failures:
        if item.get("permanent_state") not in {"open", "acknowledged"}:
            counts["skipped"] += 1
            continue
        if item.get("channel") != "email" or item.get("category") != "ct_due_reminder":
            counts["skipped"] += 1
            continue
        incident = item.get("incident_id")
        try:
            result = permanent_recipient_check(incident)
            state = str(result.get("recipientState") or "lookup_failed")
            if bool(result.get("transitionedToChanged")):
                counts["newlyChanged"] += 1
        except (LookupError, ValueError):
            counts["skipped"] += 1
            continue
        checked += 1
        if state in counts:
            counts[state] += 1
        else:
            counts["lookup_failed"] += 1
    result = {"ok": True, "checked": checked, **counts}
    _set_meta("last_permanent_recipient_refresh", json.dumps(result, separators=(",", ":")))
    return result


def permanent_recipient_retry(incident_id: object) -> dict:
    """Retry a reminder only when Mercure now resolves a different valid recipient."""
    context, target = _permanent_email_target(incident_id)
    try:
        recipient = mercure.customer_email(target["client_kind"], target["client_id"])
    except Exception:
        return {"ok": False, "state": "recipient_lookup_failed", "retryEligible": False}
    if not mail.valid_email(recipient):
        return {"ok": False, "state": "recipient_missing", "retryEligible": False}
    subject_kind = "mercure_account" if target["client_kind"] == "account" else "mercure_free"
    if privacy.any_suppressed(
        [(subject_kind,target["client_id"]),("email",recipient)],
        "ct_reminder",
    ):
        return {"ok": False, "state": "privacy_suppressed", "retryEligible": False}
    comparison = notifications.permanent_failure_recipient_state(context["incidentId"], recipient)
    if comparison.get("recipientState") != "changed":
        return {"ok": False, "state": "recipient_unchanged", "retryEligible": False}
    try:
        preflight = mail.preflight()
    except Exception:
        return {"ok": False, "state": "email_preflight_failed", "retryEligible": True}
    if not bool(preflight.get("ok")):
        return {
            "ok": False,
            "state": "waiting_email_preflight",
            "retryEligible": True,
            "preflightState": str(preflight.get("state") or "unknown"),
        }
    subject, text = _message(target["due_date"])
    delivery = notifications.send_email(
        recipient,
        subject,
        text,
        category="ct_due_reminder",
        reference=context["reference"],
    )
    if delivery.get("deferred"):
        return {
            "ok": False,
            "state": "retry_deferred",
            "incidentId": context["incidentId"],
            "recipientState": "changed",
            "retryEligible": True,
            "retryAfterSeconds": int(delivery.get("retryAfterSeconds") or 0),
        }
    if delivery.get("inFlight"):
        return {
            "ok": False,
            "state": "retry_in_flight",
            "incidentId": context["incidentId"],
            "recipientState": "changed",
            "retryEligible": True,
        }
    return {
        "ok": True,
        "state": "resent",
        "incidentId": context["incidentId"],
        "recipientState": "changed",
        "delivery": delivery,
    }


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
    sent = already = deferred = failed = missing = in_flight = permanent_suppressed = privacy_suppressed = 0
    for row in eligible:
        try:
            recipient = mercure.customer_email(row["client_kind"], row["client_id"])
            if not mail.valid_email(recipient):
                missing += 1
                continue
            subject_kind = "mercure_account" if row["client_kind"] == "account" else "mercure_free"
            if privacy.any_suppressed(
                [(subject_kind,row["client_id"]),("email",recipient)],
                "ct_reminder",
            ):
                privacy_suppressed += 1
                continue
            subject, text = _message(row["due_date"])
            delivery = notifications.send_email(
                recipient,
                subject,
                text,
                category="ct_due_reminder",
                reference=_reference(row),
            )
            if delivery.get("alreadySent"):
                already += 1
            elif delivery.get("inFlight"):
                in_flight += 1
            elif delivery.get("deferred"):
                deferred += 1
            else:
                sent += 1
        except notifications.PermanentDeliverySuppressed:
            permanent_suppressed += 1
        except Exception:
            failed += 1
    state = "partial_failure" if failed else (
        "active_with_privacy_suppressions" if privacy_suppressed else
        ("active_with_permanent_suppressions" if permanent_suppressed else "active")
    )
    result = {
        "ok": failed == 0,
        "state": state,
        "eligible": len(eligible),
        "sent": sent,
        "alreadySent": already,
        "inFlight": in_flight,
        "deferred": deferred,
        "missingRecipient": missing,
        "permanentSuppressed": permanent_suppressed,
        "privacySuppressed": privacy_suppressed,
        "failed": failed,
        "sync": sync,
    }
    _set_meta("last_process", json.dumps(result, separators=(",", ":")))
    return result


def status(now: datetime.datetime | None = None) -> dict:
    init_db()
    local = _local_now(now)
    today = local.date()
    with connect() as db:
        total = int(db.execute("SELECT COUNT(*) n FROM reminder_target").fetchone()["n"])
        quarantined = int(db.execute("SELECT COUNT(*) n FROM reminder_target WHERE quarantined=1").fetchone()["n"])
        future = int(db.execute(
            "SELECT COUNT(*) n FROM reminder_target WHERE due_date>=? AND quarantined=0",
            (today.isoformat(),),
        ).fetchone()["n"])
        next_row = db.execute(
            """SELECT due_date FROM reminder_target
               WHERE due_date>=? AND quarantined=0 ORDER BY due_date LIMIT 1""",
            (today.isoformat(),),
        ).fetchone()
    raw = _meta("last_process", "")
    try:
        last_process = json.loads(raw) if raw else None
    except Exception:
        last_process = None
    recipient_refresh_raw = _meta("last_permanent_recipient_refresh", "")
    try:
        recipient_refresh = json.loads(recipient_refresh_raw) if recipient_refresh_raw else None
    except Exception:
        recipient_refresh = None
    cursor_raw = _meta("backfill_cursor_end", "")
    floor = today - datetime.timedelta(days=BACKFILL_DAYS)
    complete = False
    if cursor_raw:
        try:
            complete = datetime.date.fromisoformat(cursor_raw) <= floor
        except ValueError:
            pass
    return {
        "ok": True,
        "sessionConnected": bool(mercure.session_status().get("connected")),
        "emailTransportConfigured": mail.configured(),
        "leadDays": list(reminders.DEFAULT_LEAD_DAYS),
        "sendHour": reminders.DEFAULT_HOUR,
        "timezone": reminders.DEFAULT_TIMEZONE,
        "inventory": total,
        "quarantinedTargets": quarantined,
        "futureDueDates": future,
        "nextDueDate": str(next_row["due_date"]) if next_row else "",
        "eligibleNow": len(_eligible(local)),
        "backfillCursorEnd": cursor_raw,
        "backfillComplete": complete,
        "lastProcess": last_process,
        "permanentRecipientRefresh": recipient_refresh,
        "privacy": "CyberCheck conserve les identifiants techniques véhicule/client et la date d’échéance, jamais l’adresse email du client.",
    }


def _loop() -> None:
    while not _STOP.is_set():
        try:
            process_once()
        except Exception:
            pass
        try:
            refresh_permanent_recipient_checks()
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