"""Read-only customer booking preflight. No Mercure writes or payment side effects."""
from __future__ import annotations

import datetime as dt
import re

import mercure_public_client
import in_site_booking_readiness as readiness


class BookingPreflightError(ValueError):
    pass


def preflight(payload: object, *, account: dict) -> dict:
    if not isinstance(payload, dict) or set(payload) != {"service", "date", "time", "vehicleId"}:
        raise BookingPreflightError("booking_request_invalid")
    service, day, time, vehicle_id = (
        str(payload[key] or "").strip() for key in ("service", "date", "time", "vehicleId")
    )
    if service not in {"technical", "fitted"}:
        raise BookingPreflightError("booking_service_invalid")
    try:
        date = dt.date.fromisoformat(day)
    except ValueError as exc:
        raise BookingPreflightError("booking_date_invalid") from exc
    if date.isoformat() != day or date < dt.date.today() or date > dt.date.today() + dt.timedelta(days=90):
        raise BookingPreflightError("booking_date_invalid")
    if not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", time):
        raise BookingPreflightError("booking_time_invalid")
    vehicles = account.get("vehicles") or []
    if not isinstance(vehicles, list) or not any(
        isinstance(v, dict) and v.get("vehicleId") == vehicle_id
        for v in vehicles
    ):
        raise BookingPreflightError("booking_vehicle_not_owned")
    available = mercure_public_client.availability(service, day)
    selected = next((
        slot for row in available.get("days", [])
        if row.get("date") == day
        for slot in row.get("slots", [])
        if str(slot.get("time")) == time and slot.get("available", True) is not False
    ), None)
    if selected is None:
        raise BookingPreflightError("booking_slot_unavailable")
    amount = selected.get("price")
    if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not 0 <= amount <= 10000:
        raise BookingPreflightError("booking_price_unverified")
    status = readiness.public_status()
    return {
        "ok": True, "service": service, "date": day, "time": time,
        "vehicleId": vehicle_id, "priceCents": round(amount * 100),
        "slotAvailableAtCheck": True, "slotHeld": False,
        "bookingConfirmed": False, "bookingEnabled": status["bookingEnabled"],
        "blockers": status["blockers"],
    }
