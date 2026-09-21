from __future__ import annotations

import datetime

import apns_gateway as apns
import email_gateway as email
import notification_broker as broker


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _gmail_delivery_evidence(broker_state: dict) -> dict:
    """Summarize real Gmail delivery history without exposing recipients or content."""
    transports = ((broker_state or {}).get("resilience") or {}).get("transports") or []
    row = next(
        (item for item in transports if isinstance(item, dict) and item.get("transport") == "email:gmail-api"),
        None,
    )
    if row is None:
        return {
            "verification": "unverified",
            "operationallyVerified": False,
            "lastSuccessAt": "",
            "lastFailureAt": "",
            "circuitOpen": False,
            "consecutiveFailures": 0,
        }

    last_success = str(row.get("lastSuccessAt") or "")
    last_failure = str(row.get("lastFailureAt") or "")
    circuit_open = bool(row.get("circuitOpen"))
    consecutive_failures = max(0, int(row.get("consecutiveFailures") or 0))
    failure_is_newer = bool(last_failure and (not last_success or last_failure > last_success))
    verified = bool(last_success) and not circuit_open and not (
        consecutive_failures and failure_is_newer
    )

    if verified:
        verification = "verified"
    elif circuit_open or failure_is_newer:
        verification = "unavailable"
    else:
        verification = "unverified"

    return {
        "verification": verification,
        "operationallyVerified": verified,
        "lastSuccessAt": last_success,
        "lastFailureAt": last_failure,
        "circuitOpen": circuit_open,
        "consecutiveFailures": consecutive_failures,
    }


def run() -> dict:
    """Run non-delivering operational checks for configured notification transports."""
    email_state = email.preflight()
    push_state = apns.preflight()
    try:
        gmail_evidence = _gmail_delivery_evidence(broker.status(1))
    except Exception:
        gmail_evidence = {
            "verification": "unavailable",
            "operationallyVerified": False,
            "lastSuccessAt": "",
            "lastFailureAt": "",
            "circuitOpen": False,
            "consecutiveFailures": 0,
        }
    email_state = dict(email_state)
    email_state["gmailDeliveryEvidence"] = gmail_evidence
    transports = list(email_state.get("transports") or [])
    transports.append({
        "transport": push_state.get("transport", "apns-http2"),
        "ready": bool(push_state.get("ready")),
        "state": push_state.get("state", "failed"),
        "status": 200 if push_state.get("ready") else 0,
        "reason": push_state.get("reason", ""),
        "keyValid": bool(push_state.get("keyValid")),
    })
    return {
        "ok": True,
        "checkedAt": _now_iso(),
        "sendsPerformed": 0,
        "email": email_state,
        "push": push_state,
        "gmailDeliveryEvidence": gmail_evidence,
        "transports": transports,
    }
