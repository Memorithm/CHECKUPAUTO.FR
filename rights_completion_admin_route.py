"""Protected HTTP adapter for DSAR completion-plan configuration.

The main server invokes payment_contract_http.handle() before its shared admin
POST gate. This adapter therefore reproduces the same fail-closed admin boundary
locally: Basic authentication, same-origin checks, MFA, strict JSON framing and
bounded request bodies must all pass before the completion planner is called.
"""
from __future__ import annotations

import json
from urllib.parse import urlsplit

import admin_mfa
import rights_completion_admin_http


ROUTE = "/api/admin/compliance/request-plan"
MAX_BODY = 32 * 1024


def _reject(handler, code: str, status: int) -> bool:
    handler.send_json({"ok": False, "error": code}, status)
    return True


def handle(handler) -> bool:
    """Handle the DSAR completion-plan mutation or return False if unrelated."""
    parsed = urlsplit(handler.path)
    if parsed.path != ROUTE:
        return False

    if not handler.authorized():
        handler.require_auth()
        return True
    if not handler._admin_origin_ok() or handler.headers.get("Sec-Fetch-Site", "") == "cross-site":
        return _reject(handler, "origin_not_allowed", 403)
    if admin_mfa.configured() and not handler._mfa_session_valid():
        handler.require_mfa()
        return True

    if parsed.query or parsed.fragment:
        return _reject(handler, "compliance_completion_plan_invalid", 400)
    if handler.command != "POST":
        return _reject(handler, "method_not_allowed", 405)
    if handler.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
        return _reject(handler, "content_type_not_allowed", 415)
    if handler.headers.get("Transfer-Encoding"):
        return _reject(handler, "compliance_completion_plan_invalid", 400)
    try:
        length = int(handler.headers.get("Content-Length", ""))
    except (TypeError, ValueError):
        return _reject(handler, "compliance_completion_plan_invalid", 400)
    if not 1 <= length <= MAX_BODY:
        return _reject(handler, "compliance_completion_plan_invalid", 400)

    try:
        raw = handler.rfile.read(length)
        if len(raw) != length:
            raise ValueError("incomplete body")
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return _reject(handler, "compliance_completion_plan_invalid", 400)

    status, body = rights_completion_admin_http.configure(payload)
    handler.send_json(body, status)
    return True
