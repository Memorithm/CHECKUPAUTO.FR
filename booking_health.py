"""Health signals for the on-site Mercure booking path.

* Mercure admin session validity (cached read-only check).
* Outcomes of ``POST /api/customer/booking/create``: provider failures and
  bookings left in ``reconciliation_required``.

Counters are kept in memory and exposed to the authenticated admin.  Alerts are
recorded through ``security_alerts`` (which may deliver them to an already
configured webhook) **only when the on-site booking flag is enabled**; with the
default configuration nothing is emitted, so no new external send exists.
"""
from __future__ import annotations

import datetime as dt
import os
import threading
import time

IN_SITE_FLAG_ENV = "CHECKUPAUTO_IN_SITE_BOOKING_ENABLED"
SESSION_CACHE_SECONDS = 60
# Errors that only mean "feature not enabled/qualified": expected while off.
DISABLED_CODES = frozenset({
    "booking_server_not_qualified", "booking_server_not_authorized",
    "booking_writer_not_qualified", "booking_writer_not_connected",
})
# Customer-side validation errors: not a provider health problem.
CUSTOMER_CODE_PREFIXES = ("booking_create_", "booking_date_", "booking_time_",
                          "booking_service_", "booking_vehicle_", "booking_request_")
SLOT_CODES = frozenset({"booking_slot_unavailable", "booking_slot_ambiguous",
                        "booking_slot_evidence_changed"})

_LOCK = threading.Lock()
_STATE: dict = {}


def _reset_for_tests() -> None:
    with _LOCK:
        _STATE.clear()
        _STATE.update({
            "session": None, "sessionCheckedMonotonic": None,
            "counters": {"confirmed": 0, "reconciliationRequired": 0, "providerFailures": 0,
                         "slotLost": 0, "customerErrors": 0, "disabled": 0},
            "lastProviderFailure": None, "lastReconciliation": None,
            "routes": {"in_site": 0, "delegated": 0}, "fallbackReasons": {},
        })


_reset_for_tests()


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def alerts_active(environ=None) -> bool:
    source = os.environ if environ is None else environ
    return str(source.get(IN_SITE_FLAG_ENV, "")).strip() == "true"


def _emit(level: str, kind: str, title: str, detail: str, dedup: str) -> None:
    if not alerts_active():
        return
    try:
        import security_alerts
        security_alerts.emit(level, kind, title, detail, metadata={"source": "booking_health"},
                             dedup_key=dedup, cooldown=1800)
    except Exception:
        # Monitoring must never break the customer request.
        pass


def session_status(*, refresh: bool = False, checker=None) -> dict:
    """Cached Mercure admin session state; never raises, never writes to Mercure."""
    with _LOCK:
        cached = _STATE["session"]
        checked = _STATE["sessionCheckedMonotonic"]
    if (not refresh and cached is not None and checked is not None
            and time.monotonic() - checked < SESSION_CACHE_SECONDS):
        return dict(cached)
    if checker is None:
        import mercure_admin_client
        checker = mercure_admin_client.session_status
    try:
        raw = checker()
        connected = isinstance(raw, dict) and raw.get("connected") is True
        state = str((raw or {}).get("state") or ("ready" if connected else "unknown"))
    except Exception:
        connected, state = False, "unexpected_error"
    result = {"connected": connected, "state": state, "checkedAt": _now_iso()}
    with _LOCK:
        _STATE["session"] = result
        _STATE["sessionCheckedMonotonic"] = time.monotonic()
    if not connected:
        _emit("high", "booking_mercure_session",
              "Session admin Mercure invalide ou expirée",
              "Les réservations sur le site retombent sur le parcours délégué Mercure. "
              "État : " + state + ". Renouveler la session (hostinger-mercure-session-sync).",
              "booking-mercure-session-" + state)
    return dict(result)


def classify(code: str) -> str:
    code = str(code or "")
    if code in DISABLED_CODES:
        return "disabled"
    if code in SLOT_CODES:
        return "slotLost"
    if code.startswith(CUSTOMER_CODE_PREFIXES):
        return "customerErrors"
    return "providerFailures"


def record_create_failure(code: str) -> str:
    kind = classify(code)
    with _LOCK:
        _STATE["counters"][kind] += 1
        if kind == "providerFailures":
            _STATE["lastProviderFailure"] = {"code": str(code)[:80], "at": _now_iso()}
    if kind == "providerFailures":
        _emit("high", "booking_mercure_write",
              "Échec de création de réservation Mercure",
              "Code : " + str(code)[:80] + ". Le client a été invité à poursuivre via le parcours délégué.",
              "booking-mercure-write-" + str(code)[:60])
    return kind


def record_create_result(result: object) -> str:
    state = result.get("state") if isinstance(result, dict) else None
    if state == "confirmed" and result.get("confirmed") is True:
        with _LOCK:
            _STATE["counters"]["confirmed"] += 1
        return "confirmed"
    with _LOCK:
        _STATE["counters"]["reconciliationRequired"] += 1
        _STATE["lastReconciliation"] = {"at": _now_iso()}
    _emit("high", "booking_mercure_reconciliation",
          "Réservation Mercure à réconcilier",
          "Une création a un résultat incertain (reconciliation_required). "
          "Vérifier dans Mercure avant toute nouvelle tentative ; aucun rejeu automatique.",
          "booking-mercure-reconciliation")
    return "reconciliationRequired"


def record_route(mode: str, reason: str) -> None:
    """Count /go/booking routing decisions (only evaluated when the flag is on)."""
    mode = "in_site" if mode == "in_site" else "delegated"
    with _LOCK:
        _STATE["routes"][mode] += 1
        if mode == "delegated" and reason:
            reasons = _STATE["fallbackReasons"]
            key = str(reason)[:60]
            if key in reasons or len(reasons) < 20:
                reasons[key] = reasons.get(key, 0) + 1


def snapshot() -> dict:
    with _LOCK:
        return {
            "alertsActive": alerts_active(),
            "session": dict(_STATE["session"]) if _STATE["session"] else None,
            "counters": dict(_STATE["counters"]),
            "lastProviderFailure": _STATE["lastProviderFailure"],
            "lastReconciliation": _STATE["lastReconciliation"],
            "routes": dict(_STATE["routes"]),
            "fallbackReasons": dict(_STATE["fallbackReasons"]),
        }
