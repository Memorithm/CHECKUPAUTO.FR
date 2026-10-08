"""Strict validation for a future authenticated centre-side Mercure booking API."""
from __future__ import annotations

import datetime as dt
import re

from mercure_booking_write_contract import BookingWriteRequest


class BookingWriteValidationError(ValueError):
    pass


def validate(request: BookingWriteRequest, *, today: dt.date | None = None) -> BookingWriteRequest:
    if not isinstance(request, BookingWriteRequest):
        raise BookingWriteValidationError("mercure_write_payload_invalid")
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,128}",request.request_key):
        raise BookingWriteValidationError("mercure_write_key_invalid")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}",request.account_id):
        raise BookingWriteValidationError("mercure_write_account_invalid")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}",request.vehicle_id):
        raise BookingWriteValidationError("mercure_write_vehicle_invalid")
    if request.service not in {"technical","fitted"}:
        raise BookingWriteValidationError("mercure_write_service_invalid")
    try:
        date=dt.date.fromisoformat(request.date)
    except (ValueError,TypeError) as exc:
        raise BookingWriteValidationError("mercure_write_date_invalid") from exc
    today=today or dt.date.today()
    if date.isoformat()!=request.date or date < today or date > today+dt.timedelta(days=90):
        raise BookingWriteValidationError("mercure_write_date_invalid")
    if not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]",request.time):
        raise BookingWriteValidationError("mercure_write_time_invalid")
    if type(request.price_cents) is not int or not 0 <= request.price_cents <= 1000000:
        raise BookingWriteValidationError("mercure_write_price_invalid")
    return request
