"""Read-only customer booking preflight. No Mercure writes or payment side effects."""
from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal, InvalidOperation
import mercure_admin_client
from customer_vehicle_booking_readiness import assess as assess_vehicle

import mercure_public_client
import in_site_booking_readiness as readiness


class BookingPreflightError(ValueError):
    pass


def preflight(payload: object, *, account: dict) -> dict:
    if not isinstance(payload, dict) or set(payload) != {"service", "date", "time", "vehicleId"}:
        raise BookingPreflightError("booking_request_invalid")
    if not all(isinstance(value,str) for value in payload.values()):
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
    today=mercure_admin_client.business_today()
    if date.isoformat() != day or date < today or date > today + dt.timedelta(days=90):
        raise BookingPreflightError("booking_date_invalid")
    if not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", time):
        raise BookingPreflightError("booking_time_invalid")
    vehicles = account.get("vehicles") or []
    selected_vehicles = [v for v in vehicles if isinstance(v,dict) and v.get("vehicleId")==vehicle_id] if isinstance(vehicles,list) else []
    if not vehicle_id or len(selected_vehicles)!=1:
        raise BookingPreflightError("booking_vehicle_not_owned")
    if assess_vehicle(selected_vehicles[0])["ready"] is not True:
        raise BookingPreflightError("booking_vehicle_incomplete")
    available = mercure_public_client.availability(service, day)
    if not isinstance(available,dict) or not isinstance(available.get("days"),list):
        raise BookingPreflightError("booking_provider_response_invalid")
    matches=[]
    for row in available["days"]:
        if not isinstance(row,dict):
            raise BookingPreflightError("booking_provider_response_invalid")
        if row.get("date")!=day:
            continue
        if not isinstance(row.get("slots"),list):
            raise BookingPreflightError("booking_provider_response_invalid")
        for slot in row["slots"]:
            if not isinstance(slot,dict):
                raise BookingPreflightError("booking_provider_response_invalid")
            if slot.get("time")==time and slot.get("available",True) is True and row.get("available",True) is True:
                matches.append(slot)
    if not matches:
        raise BookingPreflightError("booking_slot_unavailable")
    if len(matches)!=1:
        raise BookingPreflightError("booking_slot_ambiguous")
    amount=matches[0].get("price")
    if type(amount) not in (int,float):
        raise BookingPreflightError("booking_price_unverified")
    try:
        quote=Decimal(str(amount))
        cents=quote*100
        valid=quote.is_finite() and 0<=quote<=10000 and cents==cents.to_integral_value()
    except (InvalidOperation,ValueError,OverflowError):
        valid=False
    if not valid:
        raise BookingPreflightError("booking_price_unverified")
    status = readiness.public_status()
    return {
        "ok": True, "service": service, "date": day, "time": time,
        "vehicleId": vehicle_id, "priceCents": int(cents),
        "slotAvailableAtCheck": True, "slotHeld": False,
        "bookingConfirmed": False, "bookingEnabled": status["bookingEnabled"],
        "blockers": status["blockers"],
    }
