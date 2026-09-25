"""Authenticated acquiring-sheet editor; never exposes a payment operation."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from urllib.parse import urlsplit

import rights_completion_admin_route
import payment_payline_private
import payment_checkout
import payment_refund
from payment_contract_store import (ContractStore, ContractInvalid, ContractConflict,
                                    MAX_BYTES, parse_json)
from payment_core import PaymentError

ROUTE = "/api/admin/payments/contract"
ACTIVITY_ROUTE = "/api/admin/payments/activity"
REFUND_ROUTE = "/api/admin/payments/refunds"


def csrf_token(secret: str, headers, hour: int | None = None) -> str:
    period = int(time.time() // 3600) if hour is None else hour
    binding = hashlib.sha256((headers.get("Authorization", "") + "\x00" + headers.get("Cookie", "")).encode()).hexdigest()
    return hmac.new(secret.encode(), f"payments-contract:{period}:{binding}".encode(), hashlib.sha256).hexdigest()


def handle(handler, *, secret: str) -> bool:
    """Called after the global guard. Enforce auth and MFA again locally.

    Return False only for unrelated paths. The editor inherits the global request
    guard, header policy and no-store response helpers of admin_server.Handler.
    The DSAR completion-plan mutation is delegated first because admin_server
    calls this early adapter before its shared admin POST router.
    """
    if rights_completion_admin_route.handle(handler):
        return True

    parsed = urlsplit(handler.path)
    if parsed.path not in {ROUTE, ACTIVITY_ROUTE, REFUND_ROUTE}:
        return False
    if not handler.authorized():
        handler.require_auth()
        return True
    if not handler._mfa_session_valid():
        handler.require_mfa()
        return True

    def reject(code, status):
        handler.send_json({"ok": False, "error": code}, status)
        return True

    if parsed.query or parsed.fragment:
        return reject("payments_query_not_allowed", 400)
    if parsed.path == ACTIVITY_ROUTE:
        if handler.command != "GET":
            return reject("payments_method_not_allowed", 405)
        try:
            handler.send_json({"ok":True,**payment_checkout.activity()})
        except Exception:
            return reject("payments_activity_unavailable",500)
        return True
    if handler.command not in {"GET", "POST"}:
        return reject("payments_method_not_allowed", 405)
    if handler.command == "POST":
        if not handler._admin_origin_ok() or handler.headers.get("Sec-Fetch-Site", "") == "cross-site":
            return reject("payments_origin_not_allowed", 403)
        supplied = handler.headers.get("X-CheckupAuto-Payments-CSRF", "")
        current = int(time.time() // 3600)
        if not isinstance(supplied, str) or not re.fullmatch(r"[0-9a-f]{64}", supplied) or not any(
            hmac.compare_digest(supplied, csrf_token(secret, handler.headers, hour)) for hour in (current, current - 1)
        ):
            return reject("payments_csrf_invalid", 403)
        if handler.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            return reject("payments_content_type_invalid", 415)
        if handler.headers.get("Transfer-Encoding"):
            return reject("payments_transfer_encoding_invalid", 400)
        try:
            length = int(handler.headers.get("Content-Length", ""))
        except (ValueError, TypeError):
            return reject("payments_content_length_invalid", 400)
        if not 1 <= length <= MAX_BYTES:
            return reject("payments_body_too_large", 413)
    if parsed.path == REFUND_ROUTE:
        try:
            if handler.command == "GET":
                result = {
                    "ok": True,
                    **payment_refund.activity(),
                    "capability": payment_refund.capability(),
                    "csrfToken": csrf_token(secret, handler.headers),
                }
                handler.send_json(result)
                return True

            raw = handler.rfile.read(length)
            if len(raw) != length:
                raise PaymentError("refund_payload_invalid")
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError):
                raise PaymentError("refund_payload_invalid") from None
            if not isinstance(payload, dict) or set(payload) != {"requestId", "paymentId", "amountCents", "reason"}:
                raise PaymentError("refund_payload_invalid")
            result = payment_refund.execute(
                payload.get("requestId"),
                payload.get("paymentId"),
                payload.get("amountCents"),
                payload.get("reason"),
            )
            result = {
                "ok": True,
                **result,
                "capability": payment_refund.capability(),
                "csrfToken": csrf_token(secret, handler.headers),
            }
            handler.send_json(result, 200 if result["reused"] else 201)
        except payment_payline_private.PaylinePrivateConfigurationError:
            return reject("payment_provider_not_configured", 503)
        except PaymentError as exc:
            code = str(exc)
            conflicts = {
                "refund_reconciliation_required",
                "refund_request_replay_conflict",
                "refund_amount_exceeds_remaining_capture",
                "captured_payline_sandbox_payment_required",
                "provider_transaction_not_found",
                "intent_not_found",
                "payline_refund_refused",
            }
            invalid = {
                "refund_payload_invalid",
                "refund_request_id_invalid",
                "payment_id_invalid",
                "refund_amount_invalid",
                "refund_reason_invalid",
            }
            if code in conflicts:
                return reject(code, 409)
            if code in invalid:
                return reject(code, 400)
            return reject("payment_refund_unavailable", 503)
        except Exception:
            return reject("payment_refund_unavailable", 503)
        return True

    try:
        store = ContractStore()
        if handler.command == "GET":
            result = store.snapshot()
        else:
            raw = handler.rfile.read(length)
            if len(raw) != length:
                raise ContractInvalid("incomplete_body")
            result = store.update(parse_json(raw))
        result["csrfToken"] = csrf_token(secret, handler.headers)
        result["runtime"] = payment_payline_private.status()
        result["runtime"]["checkoutBasis"] = payment_checkout.capability()
        handler.send_json(result)
    except ContractConflict:
        return reject("payments_contract_conflict_reload", 409)
    except ContractInvalid:
        return reject("payments_contract_invalid", 400)
    except Exception:
        return reject("payments_contract_unavailable", 500)
    return True
