"""Independent read-only Mercure appointment evidence for booking reconciliation.

This module does not create appointments or accept browser-supplied confirmation.
"""
from __future__ import annotations

import datetime as dt
import re

import mercure_admin_client as mercure


class MercureBookingEvidenceError(RuntimeError):
    pass


def verify_appointment(*, provider_reference: object, date: object, time: object) -> bool:
    reference=str(provider_reference or "").strip()
    day=str(date or "").strip()
    clock=str(time or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}",reference):
        raise MercureBookingEvidenceError("mercure_reference_invalid")
    try:
        parsed=dt.date.fromisoformat(day)
    except (TypeError,ValueError) as exc:
        raise MercureBookingEvidenceError("mercure_booking_date_invalid") from exc
    if parsed.isoformat()!=day or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]",clock):
        raise MercureBookingEvidenceError("mercure_booking_date_invalid")
    end=(parsed+dt.timedelta(days=1)).isoformat()
    try:
        session=mercure._session()
        events=mercure._calendar_events(session,day,end)
    except Exception as exc:
        raise MercureBookingEvidenceError("mercure_calendar_unavailable") from exc
    if not isinstance(events,list):
        raise MercureBookingEvidenceError("mercure_calendar_invalid")
    matching=[event for event in events if isinstance(event,dict) and mercure._event_id(event)==reference]
    if len(matching)!=1:
        return False
    event=matching[0]
    # Never claim the booking matches an expected slot if its date/time cannot
    # be established from authoritative calendar event start.
    if event.get("extendedProps",{}).get("cancelled") is True or event.get("status") in {"cancelled","canceled"}:
        return False
    start=str(event.get("start") or "")
    try:
        parsed_start=dt.datetime.fromisoformat(start.replace("Z","+00:00"))
        if parsed_start.tzinfo is None:
            parsed_start=parsed_start.replace(tzinfo=mercure.MERCURE_TIMEZONE)
        local=parsed_start.astimezone(mercure.MERCURE_TIMEZONE)
    except (ValueError,TypeError,OverflowError):
        return False
    return local.date()==parsed and local.strftime("%H:%M")==clock
