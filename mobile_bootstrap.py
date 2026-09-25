from __future__ import annotations

from urllib.parse import urlparse
import os

import apns_gateway
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
    seo = config.get("seo") if isinstance(config, dict) else {}
    seo = seo if isinstance(seo, dict) else {}
    canonical_url = _https_url(seo.get("canonicalUrl"), "seo.canonicalUrl").rstrip("/")
    app = app_download.status(config)
    push_requested = str(os.environ.get("CYBERCHECK_MOBILE_PUSH_ENABLED", "0")).strip().lower() in {"1", "true", "yes", "on"}
    push_active = bool(push_requested and apns_gateway.status().get("configured"))
    return {
        "schemaVersion": SCHEMA_VERSION,
        "reminders": {
            "leadDays": list(reminders.DEFAULT_LEAD_DAYS),
            "hour": reminders.DEFAULT_HOUR,
            "timezone": reminders.DEFAULT_TIMEZONE,
        },
        "booking": {"url": booking_url},
        "account": {
            "url": canonical_url + "/compte",
            "reportScanUrl": canonical_url + "/compte#ct-report",
        },
        "notifications": {"remotePushActive": push_active, "localFallback": not push_active},
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
