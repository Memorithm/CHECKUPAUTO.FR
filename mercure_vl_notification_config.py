"""Explicit Mercure notification switches for customer bookings (decision 3).

Each switch maps to one Mercure appointment form field.  An unset switch adds
nothing to the payload, which keeps Mercure's current default behaviour.
Only the exact strings ``true`` and ``false`` are accepted; anything else is a
configuration error and the provider write is refused.
"""
from __future__ import annotations

import os

SWITCHES = {
    "CHECKUPAUTO_MERCURE_NOTIFY_EMAIL_CONFIRMATION": "email_confirmation_vl",
    "CHECKUPAUTO_MERCURE_NOTIFY_PRINT_CONFIRMATION": "imprime_confirmation_vl",
    "CHECKUPAUTO_MERCURE_NOTIFY_SMS_CONFIRMATION": "envoi_sms_vl",
    "CHECKUPAUTO_MERCURE_NOTIFY_SMS_REMINDER": "rappel_sms_vl",
}
FIELDS = frozenset(SWITCHES.values())


class MercureNotificationConfigError(ValueError):
    pass


def load(environ=None) -> dict:
    source = os.environ if environ is None else environ
    if not hasattr(source, "get"):
        raise MercureNotificationConfigError("mercure_notification_config_invalid")
    result = {}
    for name, field in SWITCHES.items():
        raw = source.get(name)
        if raw is None or raw == "":
            continue
        if raw not in ("true", "false"):
            raise MercureNotificationConfigError("mercure_notification_config_invalid")
        result[field] = raw
    return result


def validate(notifications: object) -> dict:
    if notifications is None:
        return {}
    if (not isinstance(notifications, dict) or set(notifications) - FIELDS
            or any(value not in ("true", "false") for value in notifications.values())):
        raise MercureNotificationConfigError("mercure_notification_config_invalid")
    return dict(notifications)
