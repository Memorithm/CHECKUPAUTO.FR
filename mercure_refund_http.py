"""Admin routes for refunding a booking paid online through Mercure.

Every route enforces, by itself: HTTP Basic admin login, an enrolled and valid
two-factor session (refunds are refused while 2FA is not configured), no query
string, and for POST same-origin, JSON only, a bounded body and a CSRF token
bound to the admin's login and session. See mercure_refund for the refund rules.
"""
from __future__ import annotations

import json
from urllib.parse import urlsplit

import admin_mfa
import mercure_admin_client
import mercure_refund
import security_guard

PREFIX = "/api/admin/mercure-refunds/"
CSRF_HEADER = "X-CheckupAuto-Refund-CSRF"
MAX_BODY = 4096
GET_ROUTES = {PREFIX + "csrf", PREFIX + "history"}
POST_ROUTES = {PREFIX + "lookup", PREFIX + "execute", PREFIX + "verify"}


def handle(handler) -> bool:
    parsed = urlsplit(handler.path)
    if not parsed.path.startswith(PREFIX):
        return False

    def reply(obj, status=200):
        handler.send_json(obj, status, {"Cache-Control": "no-store"})
        return True

    def reject(code, status):
        return reply({"ok": False, "error": code}, status)

    if not handler.authorized():
        handler.require_auth()
        return True
    if not admin_mfa.configured():
        return reject("two_factor_not_configured", 403)
    if not handler._mfa_session_valid():
        handler.require_mfa()
        return True
    if parsed.query or parsed.fragment:
        return reject("refund_query_not_allowed", 400)
    method = handler.command
    if method == "GET" and parsed.path in GET_ROUTES:
        try:
            if parsed.path == PREFIX + "csrf":
                return reply({"ok": True, "csrfToken": mercure_refund.csrf_token(handler.headers),
                              "enabled": mercure_refund.enabled(),
                              "dailyCapCents": mercure_refund.daily_cap_cents()})
            return reply({"ok": True, "refunds": mercure_refund.history()})
        except mercure_refund.RefundError as exc:
            return reject(exc.code, exc.status)
        except Exception:
            return reject("refund_unavailable", 503)
    if method != "POST" or parsed.path not in POST_ROUTES:
        return reject("refund_route_not_found", 404)
    if not handler._admin_origin_ok() or handler.headers.get("Sec-Fetch-Site", "") == "cross-site":
        return reject("origin_not_allowed", 403)
    if (handler.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower() != "application/json":
        return reject("content_type_not_allowed", 415)
    if handler.headers.get("Transfer-Encoding"):
        return reject("refund_body_invalid", 400)
    try:
        if not mercure_refund.verify_csrf(handler.headers.get(CSRF_HEADER, ""), handler.headers):
            return reject("refund_csrf_invalid", 403)
        length = int(handler.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_BODY:
            return reject("refund_body_invalid", 400)
        payload = json.loads(handler.rfile.read(length))
    except mercure_refund.RefundError as exc:
        return reject(exc.code, exc.status)
    except (ValueError, UnicodeDecodeError):
        return reject("refund_body_invalid", 400)
    try:
        if parsed.path == PREFIX + "lookup":
            return reply(mercure_refund.lookup(payload, headers=handler.headers))
        if parsed.path == PREFIX + "verify":
            return reply(mercure_refund.verify_uncertain(payload))
        return reply(mercure_refund.execute(payload, headers=handler.headers,
                                            verify_code=admin_mfa.verify_step_up))
    except mercure_refund.RefundError as exc:
        if exc.code == "refund_second_factor_invalid" and getattr(handler, "_security_client", ""):
            try:
                security_guard.auth_failure(handler._security_client, parsed.path)
            except Exception:
                pass
        return reject(exc.code, exc.status)
    except mercure_admin_client.MercureSessionError:
        return reject("mercure_session_unavailable", 503)
    except Exception:
        return reject("refund_unavailable", 503)
