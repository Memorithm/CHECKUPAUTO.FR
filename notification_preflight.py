from __future__ import annotations

import datetime

import apns_gateway as apns
import email_gateway as email
import gmail_operational_evidence as gmail_evidence


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def run() -> dict:
    """Run non-delivering operational checks for configured notification transports."""
    email_state = email.preflight()
    push_state = apns.preflight()
    try:
        delivery_evidence = gmail_evidence.status()
    except Exception:
        delivery_evidence = {
            "verification": "unavailable",
            "operationallyVerified": False,
            "lastSuccessAt": "",
            "lastFailureAt": "",
            "circuitOpen": False,
            "consecutiveFailures": 0,
        }
    email_state = dict(email_state)
    email_state["gmailDeliveryEvidence"] = delivery_evidence
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
        "gmailDeliveryEvidence": delivery_evidence,
        "transports": transports,
    }
