"""Strict independent date/time verification for a Mercure appointment row."""
from __future__ import annotations
import datetime as dt
from zoneinfo import ZoneInfo

PARIS=ZoneInfo("Europe/Paris")


def verify(*, row: dict, expected_date: str, expected_time: str) -> bool:
    if not isinstance(row,dict):
        raise ValueError("mercure_appointment_row_invalid")
    raw=row.get("date_rdv")
    if not isinstance(raw,str) or not raw:
        raise ValueError("mercure_appointment_datetime_missing")
    try:
        timestamp=dt.datetime.fromisoformat(raw.replace("Z","+00:00"))
        date=dt.date.fromisoformat(expected_date)
        time=dt.time.fromisoformat(expected_time)
    except (ValueError,TypeError) as exc:
        raise ValueError("mercure_appointment_datetime_invalid") from exc
    if timestamp.tzinfo is None:
        timestamp=timestamp.replace(tzinfo=PARIS)
    local=timestamp.astimezone(PARIS)
    if local.date()!=date or local.hour!=time.hour or local.minute!=time.minute:
        raise ValueError("mercure_appointment_slot_mismatch")
    return True
