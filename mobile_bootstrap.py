from __future__ import annotations

from urllib.parse import urlparse

import app_download
import referral_engine as referrals
import reminder_engine as reminders

SCHEMA_VERSION = 1


def _https_url(value: object, name: str) -> str:
    raw = str(value or "").strip()
    try:
        parsed = urlparse(raw)
    except Exception as exc:
        raise ValueError(f"{name} invalide") from exc
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError(f"{name} invalide")
    return raw


def status(config: dict) -> dict:
    business = config.get("business") if isinstance(config, dict) else {}
    business = business if isinstance(business, dict) else {}
    booking_url = _https_url(business.get("bookingUrl"), "business.bookingUrl")
    app = app_download.status(config)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "reminders": {
            "leadDays": list(reminders.DEFAULT_LEAD_DAYS),
            "hour": reminders.DEFAULT_HOUR,
            "timezone": reminders.DEFAULT_TIMEZONE,
        },
        "booking": {"url": booking_url},
        "referral": {
            "rewardCents": referrals.configured_reward_cents(),
            "currency": "EUR",
        },
        "app": {
            "landingUrl": app["landingUrl"],
            "available": bool(app["ios"]["available"]),
            "downloadPath": app["ios"]["downloadPath"],
        },
    }
