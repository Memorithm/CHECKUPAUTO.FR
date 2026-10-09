"""Server-only booking create gate; never enables an unqualified Mercure writer."""
from __future__ import annotations
import re

import customer_booking_api
import in_site_booking_readiness


class BookingCreateInvalid(ValueError):
    pass


class BookingCreateUnavailable(RuntimeError):
    pass


def create(payload: object, *, account: dict) -> dict:
    if not isinstance(payload,dict) or set(payload)!={"service","date","time","vehicleId","requestKey"}:
        raise BookingCreateInvalid("booking_create_request_invalid")
    key=payload.get("requestKey")
    if not isinstance(key,str) or not re.fullmatch(r"[A-Za-z0-9_-]{20,128}",key):
        raise BookingCreateInvalid("booking_create_key_invalid")
    try:
        preflight=customer_booking_api.preflight(
            {name:payload[name] for name in ("service","date","time","vehicleId")},
            account=account)
    except customer_booking_api.BookingPreflightError as exc:
        raise BookingCreateInvalid(str(exc)) from exc
    if preflight.get("bookingEnabled") is not True or in_site_booking_readiness.public_status().get("bookingEnabled") is not True:
        raise BookingCreateUnavailable("booking_writer_not_qualified")
    # Explicit fail-closed boundary until an authorized server-only provider
    # is wired and its evidence has passed production homologation.
    raise BookingCreateUnavailable("booking_writer_not_connected")
