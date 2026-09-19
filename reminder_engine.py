from __future__ import annotations

import datetime
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE = "Europe/Paris"
DEFAULT_LEAD_DAYS = (60, 30, 15, 7, 1)
DEFAULT_HOUR = 9


@dataclass(frozen=True)
class ReminderEvent:
    days_before: int
    due_date: datetime.date
    send_at: datetime.datetime

    def as_dict(self) -> dict:
        return {
            "daysBefore": self.days_before,
            "dueDate": self.due_date.isoformat(),
            "sendAt": self.send_at.isoformat(),
        }


def _timezone(name: str) -> ZoneInfo:
    raw = str(name or DEFAULT_TIMEZONE).strip()
    try:
        return ZoneInfo(raw)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("Fuseau horaire invalide") from exc


def _due_date(value: object) -> datetime.date:
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    raw = str(value or "").strip()
    try:
        return datetime.date.fromisoformat(raw)
    except Exception as exc:
        raise ValueError("Date d’échéance invalide") from exc


def _lead_days(values) -> tuple[int, ...]:
    if values is None:
        return DEFAULT_LEAD_DAYS
    clean = []
    for raw in values:
        try:
            value = int(raw)
        except Exception as exc:
            raise ValueError("Délai de rappel invalide") from exc
        if value < 0 or value > 3650:
            raise ValueError("Délai de rappel invalide")
        if value not in clean:
            clean.append(value)
    if not clean:
        raise ValueError("Au moins un délai de rappel est requis")
    return tuple(sorted(clean, reverse=True))


def plan(
    due_date: object,
    *,
    now: datetime.datetime | None = None,
    timezone: str = DEFAULT_TIMEZONE,
    lead_days=None,
    hour: int = DEFAULT_HOUR,
) -> list[ReminderEvent]:
    due = _due_date(due_date)
    tz = _timezone(timezone)
    hour = int(hour)
    if hour < 0 or hour > 23:
        raise ValueError("Heure de rappel invalide")
    if now is None:
        current = datetime.datetime.now(tz)
    elif now.tzinfo is None:
        current = now.replace(tzinfo=tz)
    else:
        current = now.astimezone(tz)
    events = []
    for days_before in _lead_days(lead_days):
        target_day = due - datetime.timedelta(days=days_before)
        send_at = datetime.datetime.combine(
            target_day,
            datetime.time(hour=hour),
            tzinfo=tz,
        )
        if send_at <= current:
            continue
        events.append(
            ReminderEvent(
                days_before=days_before,
                due_date=due,
                send_at=send_at,
            )
        )
    events.sort(key=lambda item: item.send_at)
    return events


def plan_dicts(
    due_date: object,
    *,
    now: datetime.datetime | None = None,
    timezone: str = DEFAULT_TIMEZONE,
    lead_days=None,
    hour: int = DEFAULT_HOUR,
) -> list[dict]:
    return [
        item.as_dict()
        for item in plan(
            due_date,
            now=now,
            timezone=timezone,
            lead_days=lead_days,
            hour=hour,
        )
    ]


def next_reminder(
    due_date: object,
    *,
    now: datetime.datetime | None = None,
    timezone: str = DEFAULT_TIMEZONE,
    lead_days=None,
    hour: int = DEFAULT_HOUR,
) -> dict | None:
    events = plan_dicts(
        due_date,
        now=now,
        timezone=timezone,
        lead_days=lead_days,
        hour=hour,
    )
    return events[0] if events else None
