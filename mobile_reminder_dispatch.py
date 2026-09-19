from __future__ import annotations

import datetime
import os
import threading
from zoneinfo import ZoneInfo

import apns_gateway
import mobile_devices
import notification_broker as notifications
import reminder_engine as reminders

INTERVAL_SECONDS = 3600
_STOP = threading.Event()
_THREAD = None


def _enabled() -> bool:
    return str(os.environ.get("CYBERCHECK_MOBILE_PUSH_ENABLED", "0")).strip().lower() in {"1", "true", "yes", "on"}


def _local_now(now: datetime.datetime | None = None) -> datetime.datetime:
    tz = ZoneInfo(reminders.DEFAULT_TIMEZONE)
    if now is None:
        return datetime.datetime.now(tz)
    if now.tzinfo is None:
        return now.replace(tzinfo=tz)
    return now.astimezone(tz)


def _eligible(now: datetime.datetime | None = None) -> list[dict]:
    local = _local_now(now)
    today = local.date()
    end = today + datetime.timedelta(days=max(reminders.DEFAULT_LEAD_DAYS))
    rows = mobile_devices.due_targets(today.isoformat(), end.isoformat())
    eligible: list[dict] = []
    for row in rows:
        due = datetime.date.fromisoformat(row["due_date"])
        lead = (due - today).days
        if lead in reminders.DEFAULT_LEAD_DAYS:
            item = dict(row)
            item["days_before"] = lead
            eligible.append(item)
    return eligible


def _message(due_date: str, days_before: int) -> tuple[str, str]:
    due = datetime.date.fromisoformat(due_date)
    due_fr = due.strftime("%d/%m/%Y")
    title = "Contrôle technique à prévoir"
    body = (
        f"Votre échéance est prévue le {due_fr} "
        f"(dans {days_before} jour{'s' if days_before > 1 else ''}). "
        "Pensez à réserver votre contrôle Checkup Auto."
    )
    return title, body


def _reference(row: dict) -> str:
    return f"mobile-ct:{row['deadline_id']}:{row['due_date']}:j{row['days_before']}"


def process_once(now: datetime.datetime | None = None) -> dict:
    local = _local_now(now)
    eligible = _eligible(local)
    transport = apns_gateway.status()
    if local.hour < reminders.DEFAULT_HOUR:
        return {"ok": True, "state": "before_send_window", "eligible": 0, "sent": 0}
    if not _enabled():
        return {"ok": True, "state": "waiting_activation", "eligible": len(eligible), "sent": 0}
    if not transport.get("configured"):
        return {"ok": True, "state": "waiting_apns_credentials", "eligible": len(eligible), "sent": 0}

    sent = already = in_flight = failed = retired = transient = provider_failures = 0
    for row in eligible:
        try:
            title, body = _message(row["due_date"], row["days_before"])
            delivery = notifications.send_push(
                row["device_token"], title, body,
                category="ct_due_reminder",
                reference=_reference(row),
                environment=row["environment"],
                data={
                    "deadlineId": row["deadline_id"],
                    "dueDate": row["due_date"],
                    "daysBefore": row["days_before"],
                },
            )
            if delivery.get("alreadySent"):
                already += 1
            elif delivery.get("inFlight"):
                in_flight += 1
            else:
                sent += 1
        except apns_gateway.APNSError as exc:
            if exc.token_invalid:
                result = mobile_devices.disable_invalid_token(
                    row["installation_id"], row["device_token"], f"apns:{exc.reason}"
                )
                if result.get("disabled"):
                    retired += 1
                continue
            failed += 1
            if exc.retryable:
                transient += 1
            if exc.provider_error:
                provider_failures += 1
                break
        except Exception:
            failed += 1
    state = "active"
    if provider_failures:
        state = "provider_failure"
    elif failed:
        state = "partial_failure"
    elif retired:
        state = "active_tokens_retired"
    return {
        "ok": failed == 0,
        "state": state,
        "eligible": len(eligible),
        "sent": sent,
        "alreadySent": already,
        "inFlight": in_flight,
        "retiredTokens": retired,
        "transientFailures": transient,
        "providerFailures": provider_failures,
        "failed": failed,
    }


def status(now: datetime.datetime | None = None) -> dict:
    local = _local_now(now)
    eligible = _eligible(local) if local.hour >= reminders.DEFAULT_HOUR else []
    transport = apns_gateway.status()
    return {
        "ok": True,
        "enabled": _enabled(),
        "transportConfigured": bool(transport.get("configured")),
        "active": bool(_enabled() and transport.get("configured")),
        "eligibleNow": len(eligible),
        "leadDays": list(reminders.DEFAULT_LEAD_DAYS),
        "sendHour": reminders.DEFAULT_HOUR,
        "timezone": reminders.DEFAULT_TIMEZONE,
        "privacy": "Les rappels push utilisent uniquement un identifiant d’échéance opaque et sa date, sans immatriculation ni donnée Mercure.",
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
    if interval != INTERVAL_SECONDS:
        INTERVAL_SECONDS = max(300, int(interval))
    if _THREAD and _THREAD.is_alive():
        return
    _STOP.clear()
    _THREAD = threading.Thread(target=_loop, daemon=True, name="CyberCheckMobileReminderDispatch")
    _THREAD.start()


def stop() -> None:
    _STOP.set()
