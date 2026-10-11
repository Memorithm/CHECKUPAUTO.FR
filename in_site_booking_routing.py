"""Choose between the on-site booking journey and the delegated MercureWeb path.

Default (flag absent/off): always ``delegated`` with no I/O at all, so ``/go/booking``
keeps producing the exact legacy page.  With the flag on, any missing
prerequisite (readiness closed, provider write disabled, sign-off missing,
Mercure admin session invalid, unsupported service or slot, any error) falls
back to ``delegated`` automatically.
"""
from __future__ import annotations

import datetime as dt
import re
import unicodedata

import booking_health
import in_site_booking_readiness
import mercure_public_client


def _fold(value: object) -> str:
    raw = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
    return " ".join(raw.lower().split())


def service_key(label: object) -> str:
    wanted = _fold(label)
    matches = [key for key, item in mercure_public_client.SERVICES.items()
               if key in ("technical", "fitted") and _fold(item.get("label")) == wanted]
    return matches[0] if len(matches) == 1 else ""


def _slot_valid(date: object, time: object) -> bool:
    if not isinstance(date, str) or not isinstance(time, str):
        return False
    try:
        parsed = dt.date.fromisoformat(date)
    except ValueError:
        return False
    return parsed.isoformat() == date and bool(re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", time))


def _delegated(reason: str) -> dict:
    return {"mode": "delegated", "reason": reason}


def decide(*, service_label: object, preferred_date: object, preferred_time: object,
           vehicle: object, environ=None, session_checker=None) -> dict:
    if not in_site_booking_readiness.in_site_flag_enabled(environ):
        return _delegated("in_site_flag_off")
    try:
        key = service_key(service_label)
        if not key:
            result = _delegated("service_not_supported")
        elif not _slot_valid(preferred_date, preferred_time):
            result = _delegated("slot_missing")
        elif not isinstance(vehicle, dict) or not str(vehicle.get("vehicleId") or "").strip():
            result = _delegated("vehicle_missing")
        elif in_site_booking_readiness.public_status(environ=environ).get("bookingEnabled") is not True:
            result = _delegated("readiness_closed")
        elif booking_health.session_status(checker=session_checker).get("connected") is not True:
            result = _delegated("mercure_session_invalid")
        else:
            result = {"mode": "in_site", "reason": "", "service": key}
    except Exception:
        result = _delegated("routing_error")
    booking_health.record_route(result["mode"], result["reason"])
    return result
