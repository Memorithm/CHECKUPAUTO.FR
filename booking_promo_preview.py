"""Four fictitious €5-off slots for the 2026-10-08 staging visual check.

This module never reads or writes Mercure availability, customers or prices.
The route is accessible only on the explicitly configured Hostinger staging
hostname with two opt-in environment guards, and expires on 2026-10-11.
"""
from __future__ import annotations

import datetime as dt
import hmac
import os
from zoneinfo import ZoneInfo

import mercure_public_client as mercure_public

FIRST_DAY = dt.date(2026, 10, 8)
LAST_DAY = dt.date(2026, 10, 11)
DEMO_SLOTS = (
    ("2026-10-09", "vendredi", "9", "octobre", "10:30"),
    ("2026-10-09", "vendredi", "9", "octobre", "15:30"),
    ("2026-10-10", "samedi", "10", "octobre", "09:30"),
    ("2026-10-10", "samedi", "10", "octobre", "11:30"),
)
SAVING_EUR = 5.0


def enabled(request_host, *, environ=None, today=None):
    """Require stage identity, exact requested host, explicit flag and date."""
    env = os.environ if environ is None else environ
    if (env.get("CYBERCHECK_RUNTIME_ENV") != "staging"
            or env.get("CYBERCHECK_PROMO_PREVIEW") != "1"
            or env.get("CYBERCHECK_LOW_DEMAND_PROMO_PUBLISH") == "1"):
        return False
    trusted_host = str(env.get("CYBERCHECK_STAGING_HOST") or "").strip().lower()
    request_host = str(request_host or "").strip().lower().split(":")[0]
    if not trusted_host or not request_host:
        return False
    if not hmac.compare_digest(request_host, trusted_host):
        return False
    if today is None:
        today = dt.datetime.now(ZoneInfo("Europe/Paris")).date()
    return FIRST_DAY <= today <= LAST_DAY


def build(service_key, incentives):
    """Return test-only display data. These slots are NOT Mercure inventory."""
    meta = mercure_public.service(service_key)
    base = round(float(meta["basePrice"]), 2)
    final = round(base - SAVING_EUR, 2)
    if final <= 0:
        raise ValueError("Invalid demo pricing")
    days = []
    for date in ("2026-10-09", "2026-10-10"):
        rows = [slot for slot in DEMO_SLOTS if slot[0] == date]
        days.append({
            "date": date,
            "weekday": rows[0][1],
            "day": rows[0][2],
            "month": rows[0][3],
            "available": True,
            "slots": [{
                "time": slot[4],
                "basePrice": base,
                "price": final,
                "promotion": True,
                "saving": SAVING_EUR,
                "discountPercent": round(100 * SAVING_EUR / base, 1),
                "lowDemandOffer": {"kind": "stage-preview", "savingEuro": SAVING_EUR},
                "previewOnly": True,
            } for slot in rows],
        })
    return {
        "service": {"key": service_key, **meta},
        "providerBasePrice": base,
        "startDate": "2026-10-09",
        "days": days,
        "incentives": incentives,
        "preview": {
            "mode": "staging-visual-only",
            "bookable": False,
            "providerPriceVerified": False,
            "slotCount": 4,
            "expiresAt": LAST_DAY.isoformat(),
        },
    }
