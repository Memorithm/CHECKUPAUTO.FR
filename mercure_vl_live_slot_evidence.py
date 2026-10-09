"""Read-only, uncached slot evidence for an independently observed single VL line.

The public availability endpoint does not identify a line. It can only be
joined to the administrative resource list when that list contains exactly one
resource, strictly classified VL. Multiple resources fail closed. An available
slot is an observation, never a hold, a successful write or an activation grant.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from decimal import Decimal, InvalidOperation

import mercure_admin_client as admin
import mercure_public_client as public


class MercureVlSlotEvidenceError(ValueError):
    pass


def _reject(code: str):
    raise MercureVlSlotEvidenceError(code)


def _time(value: object) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value):
        _reject("mercure_slot_time_invalid")
    return int(value[:2]) * 60 + int(value[3:])


def _day(value: object) -> dt.date:
    if not isinstance(value, str):
        _reject("mercure_slot_date_invalid")
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError:
        _reject("mercure_slot_date_invalid")
    if parsed.isoformat() != value:
        _reject("mercure_slot_date_invalid")
    return parsed


def _number(value: object) -> int:
    if type(value) not in (str, int) or not re.fullmatch(r"[0-9]{1,4}", str(value)):
        _reject("mercure_slot_response_invalid")
    return int(value)


def _price(value: object) -> int:
    if type(value) not in (str, int, float) or len(str(value)) > 32:
        _reject("mercure_slot_price_unverified")
    try:
        amount = Decimal(str(value))
        cents = amount * 100
        if not amount.is_finite() or not 0 <= amount <= 10000 or cents != cents.to_integral_value():
            _reject("mercure_slot_price_unverified")
        return int(cents)
    except (InvalidOperation, ValueError, OverflowError):
        _reject("mercure_slot_price_unverified")


def _within_hours(resource: dict, day: dt.date, start: int, duration: int) -> bool:
    hours = resource.get("businessHours")
    if not isinstance(hours, list) or not 1 <= len(hours) <= 56:
        _reject("mercure_line_hours_unverified")
    intervals = []
    weekday = (day.weekday() + 1) % 7  # FullCalendar: Sunday = 0.
    for item in hours:
        if not isinstance(item, dict):
            _reject("mercure_line_hours_unverified")
        weekdays = item.get("daysOfWeek")
        if isinstance(weekdays, str):
            try:
                weekdays = json.loads(weekdays)
            except (ValueError, TypeError):
                _reject("mercure_line_hours_unverified")
        if (not isinstance(weekdays, list) or not 1 <= len(weekdays) <= 7
                or any(type(d) is not int or not 0 <= d <= 6 for d in weekdays)):
            _reject("mercure_line_hours_unverified")
        lo, hi = _time(item.get("startTime")), _time(item.get("endTime"))
        if hi <= lo:
            _reject("mercure_line_hours_unverified")
        if weekday in weekdays:
            intervals.append((lo, hi))
    # Adjacent opening periods form one uninterrupted interval.
    covered = start
    for lo, hi in sorted(intervals):
        if lo <= covered < hi:
            covered = hi
        if covered >= start + duration:
            return True
    return False


def qualify(*, service: str, date: str, time: str, line_id: str,
            resources: object, availability: object) -> dict:
    meta = public.service(service)
    day, start = _day(date), _time(time)
    if not isinstance(line_id, str) or not re.fullmatch(r"[0-9]{1,12}", line_id):
        _reject("mercure_line_id_invalid")
    if not isinstance(resources, list) or len(resources) != 1:
        _reject("mercure_line_not_unique")
    resource = resources[0]
    if not isinstance(resource, dict) or resource.get("children"):
        _reject("mercure_line_resource_invalid")
    props = resource.get("extendedProps")
    if (not isinstance(props, dict) or props.get("typeVl") is not True
            or props.get("typePl") is not False or props.get("typeCl") is not False):
        _reject("mercure_line_not_exclusive_vl")
    resource_id = resource.get("id")
    if type(resource_id) not in (str, int) or str(resource_id) != line_id:
        _reject("mercure_line_mismatch")
    if not _within_hours(resource, day, start, meta["duration"]):
        _reject("mercure_slot_outside_line_hours")
    if (not isinstance(availability, dict) or type(availability.get("status")) is not int
            or availability["status"] != 200):
        _reject("mercure_slot_response_invalid")
    if _number(availability.get("duree")) != meta["duration"]:
        _reject("mercure_slot_duration_mismatch")
    message = availability.get("message")
    days = message.get("donnees") if isinstance(message, dict) else None
    if not isinstance(days, list) or not 1 <= len(days) <= 32:
        _reject("mercure_slot_response_invalid")
    matches, requested_days = [], 0
    for row in days:
        data = row.get("date") if isinstance(row, dict) else None
        month = data.get("mois") if isinstance(data, dict) else None
        if not isinstance(month, dict):
            _reject("mercure_slot_response_invalid")
        try:
            observed_day = dt.date(_number(data.get("annee")),
                                   _number(month.get("numero")), _number(data.get("jour")))
        except (ValueError, TypeError):
            _reject("mercure_slot_response_invalid")
        if observed_day != day:
            continue
        requested_days += 1
        for period in ("AM", "PM"):
            part = row.get(period)
            if not isinstance(part, dict) or not isinstance(part.get("creneaux"), list):
                _reject("mercure_slot_response_invalid")
            if len(part["creneaux"]) > 288:
                _reject("mercure_slot_response_invalid")
            for slot in part["creneaux"]:
                if not isinstance(slot, dict):
                    _reject("mercure_slot_response_invalid")
                if slot.get("heure") == time:
                    matches.append(slot)
    if requested_days > 1 or len(matches) > 1:
        _reject("mercure_slot_ambiguous")
    if len(matches) != 1:
        _reject("mercure_slot_unavailable")
    return {"observed": True, "lineId": line_id, "centreType": "1",
            "slotAvailable": True, "slotHeld": False, "date": date, "time": time,
            "service": service, "serviceId": meta["id"], "duration": str(meta["duration"]),
            "priceCents": _price(matches[0].get("prix")),
            "source": "mercure-single-vl-resource-and-live-availability"}


def load(*, service: str, date: str, time: str, line_id: str) -> dict:
    """Re-read both provider sources. Never use the public display cache."""
    day = _day(date)
    _time(time)
    today = admin.business_today()
    if not today <= day <= today + dt.timedelta(days=90):
        _reject("mercure_slot_date_out_of_range")
    meta = public.service(service)
    session = admin._session()
    try:
        response = admin._check_auth(session.get(
            admin.BASE + "/admin/ligne_centre/json", timeout=20, allow_redirects=False))
        response.raise_for_status()
        resources = response.json()
    finally:
        session.close()
    raw = public._provider_availability(meta["id"], date)
    return qualify(service=service, date=date, time=time, line_id=line_id,
                   resources=resources, availability=raw)
