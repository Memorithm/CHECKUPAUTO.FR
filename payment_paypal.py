"""PayPal Orders v2 sandbox connector. No live endpoint is implemented.

Only authenticated API responses (or verified webhooks followed by an API read)
may produce capture evidence. Provider bodies and payer details are not returned
or logged. The caller persists order binding before allowing a capture.
"""
from __future__ import annotations

import base64
import hashlib
import http.client
import json
import ssl
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlsplit

from payment_core import Intent, PaymentError, VerifiedEvent, decimal_amount, parse_eur, text

API_HOST = "api-m.sandbox.paypal.com"
MAX_BODY = 128 * 1024


def strict_json(raw: bytes) -> dict:
    def pairs(items):
        obj = {}
        for key, value in items:
            if key in obj:
                raise PaymentError("duplicate_json_field")
            obj[key] = value
        return obj
    if not isinstance(raw, bytes) or len(raw) > MAX_BODY:
        raise PaymentError("provider_body_invalid")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError, RecursionError):
        raise PaymentError("provider_body_invalid") from None
    if not isinstance(value, dict):
        raise PaymentError("provider_body_invalid")
    return value


def origin_url(value: str) -> str:
    if not isinstance(value, str) or len(value) > 200 or any(c.isspace() for c in value):
        raise PaymentError("https_origin_required")
    try:
        u = urlsplit(value)
        valid = (u.scheme == "https" and u.hostname and u.username is None and
                 u.password is None and u.port in (None, 443) and u.path in ("", "/")
                 and not u.query and not u.fragment and "\\" not in value)
    except ValueError:
        valid = False
    if not valid:
        raise PaymentError("https_origin_required")
    return value.rstrip("/")


def request_id(intent: Intent, action: str) -> str:
    if action not in {"create", "capture"}:
        raise PaymentError("action_invalid")
    return hashlib.sha256(("paypal:sandbox:" + intent.payment_id + ":" + action).encode()).hexdigest()[:32]


@dataclass(frozen=True)
class PayPalSandboxConfig:
    client_id: str = field(repr=False)
    client_secret: str = field(repr=False)
    merchant_id: str
    return_origin: str
    webhook_id: str = field(default="", repr=False)

    def __post_init__(self):
        text(self.client_id, r"[A-Za-z0-9_-]{8,256}", "client_id_invalid")
        text(self.client_secret, r"[A-Za-z0-9_-]{8,256}", "client_secret_invalid")
        text(self.merchant_id, r"[A-Z0-9]{13}", "merchant_id_invalid")
        origin_url(self.return_origin)
        if self.webhook_id:
            text(self.webhook_id, r"[A-Za-z0-9-]{1,80}", "webhook_id_invalid")


def create_order_payload(intent: Intent, config: PayPalSandboxConfig) -> dict:
    if intent.provider != "paypal" or intent.environment != "sandbox":
        raise PaymentError("sandbox_paypal_required")
    origin = origin_url(config.return_origin)
    return {
        "intent": "CAPTURE",
        "purchase_units": [{
            "reference_id": intent.payment_id,
            "custom_id": intent.payment_id,
            "payee": {"merchant_id": config.merchant_id},
            "amount": {"currency_code": "EUR", "value": decimal_amount(intent.amount_cents)},
        }],
        "payment_source": {"paypal": {"experience_context": {
            "shipping_preference": "NO_SHIPPING", "user_action": "PAY_NOW",
            "return_url": origin + "/payments/paypal/return",
            "cancel_url": origin + "/payments/paypal/cancel",
        }}},
    }


def capture_evidence(data: dict, intent: Intent, merchant_id: str) -> VerifiedEvent:
    """Validate an authenticated Orders API response; never a browser JSON body."""
    try:
        units = data["purchase_units"]
        if (intent.provider != "paypal" or not intent.provider_reference or
            data["id"] != intent.provider_reference or data["status"] != "COMPLETED" or
            len(units) != 1):
            raise ValueError
        unit = units[0]
        if (unit["reference_id"] != intent.payment_id or unit["custom_id"] != intent.payment_id or
            unit["payee"]["merchant_id"] != merchant_id or
            unit["amount"]["currency_code"] != "EUR" or
            parse_eur(unit["amount"]["value"]) != intent.amount_cents):
            raise ValueError
        captures = unit["payments"]["captures"]
        if len(captures) != 1:
            raise ValueError
        capture = captures[0]
        if (capture["status"] != "COMPLETED" or capture["final_capture"] is not True or
            capture["amount"]["currency_code"] != "EUR" or
            parse_eur(capture["amount"]["value"]) != intent.amount_cents):
            raise ValueError
        capture_id = text(capture["id"], r"[A-Z0-9]{8,32}", "capture_id_invalid")
    except (KeyError, IndexError, TypeError, ValueError):
        raise PaymentError("capture_not_verified") from None
    return VerifiedEvent(intent.payment_id, "paypal", intent.provider_reference,
                         "capture:" + capture_id, "captured", intent.amount_cents)


class SandboxPayPal:
    def __init__(self, config: PayPalSandboxConfig):
        self.config = config

    def _request(self, method: str, path: str, headers: dict, body: bytes | None) -> dict:
        # Never follow response links, redirects or callback-supplied URLs.
        connection = http.client.HTTPSConnection(API_HOST, timeout=10, context=ssl.create_default_context())
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            raw = response.read(MAX_BODY + 1)
            if not 200 <= response.status < 300 or len(raw) > MAX_BODY:
                raise PaymentError("paypal_request_failed")
            return strict_json(raw)
        except (OSError, http.client.HTTPException):
            raise PaymentError("paypal_unavailable") from None
        finally:
            connection.close()

    def _api(self, method: str, path: str, data: dict | None = None, key: str = "") -> dict:
        basic = base64.b64encode((self.config.client_id + ":" + self.config.client_secret).encode()).decode()
        token = self._request("POST", "/v1/oauth2/token", {
            "Authorization": "Basic " + basic, "Content-Type": "application/x-www-form-urlencoded",
        }, b"grant_type=client_credentials")
        access = text(token.get("access_token"), r"[A-Za-z0-9._~-]{1,4096}", "oauth_response_invalid")
        if str(token.get("token_type", "")).lower() != "bearer":
            raise PaymentError("oauth_response_invalid")
        headers = {"Authorization": "Bearer " + access, "Content-Type": "application/json", "Prefer": "return=representation"}
        if key:
            headers["PayPal-Request-ID"] = key
        return self._request(method, path, headers, None if data is None else json.dumps(data, separators=(",", ":")).encode())

    def create_order(self, intent: Intent) -> dict:
        if intent.provider_reference or intent.state != "created":
            raise PaymentError("new_unbound_intent_required")
        data = self._api("POST", "/v2/checkout/orders", create_order_payload(intent, self.config), request_id(intent, "create"))
        try:
            order_id = text(data["id"], r"[A-Z0-9]{8,32}", "order_id_invalid")
            if data["status"] not in {"CREATED", "PAYER_ACTION_REQUIRED"}:
                raise ValueError
            candidates = [link for link in data["links"] if link.get("rel") in {"approve", "payer-action"}]
            if len(candidates) != 1:
                raise ValueError
            url = candidates[0]["href"]
            u = urlsplit(url)
            if (u.scheme != "https" or u.hostname != "www.sandbox.paypal.com" or
                u.port not in (None, 443) or u.username is not None or u.password is not None or
                u.path != "/checkoutnow" or u.fragment or
                parse_qs(u.query, keep_blank_values=True).get("token") != [order_id]):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise PaymentError("paypal_approval_not_verified") from None
        return {"orderId": order_id, "approvalUrl": url, "environment": "sandbox", "paid": False}

    def capture_order(self, intent: Intent) -> VerifiedEvent:
        if intent.provider != "paypal" or not intent.provider_reference or intent.state == "captured":
            raise PaymentError("bound_uncaptured_paypal_order_required")
        order_id = text(intent.provider_reference, r"[A-Z0-9]{8,32}", "order_id_invalid")
        data = self._api("POST", "/v2/checkout/orders/" + order_id + "/capture", {}, request_id(intent, "capture"))
        return capture_evidence(data, intent, self.config.merchant_id)

    def verify_webhook(self, intent: Intent, raw: bytes, headers: dict[str, str]) -> VerifiedEvent:
        if not self.config.webhook_id or intent.provider != "paypal" or not intent.provider_reference:
            raise PaymentError("webhook_configuration_required")
        event = strict_json(raw)
        lowered = {}
        for name, value in headers.items():
            key = name.lower()
            if key in lowered:
                raise PaymentError("webhook_header_invalid")
            lowered[key] = value
        fields = {}
        for target, header in {
            "auth_algo": "paypal-auth-algo", "cert_url": "paypal-cert-url",
            "transmission_id": "paypal-transmission-id", "transmission_sig": "paypal-transmission-sig",
            "transmission_time": "paypal-transmission-time",
        }.items():
            fields[target] = text(lowered.get(header), r"[^\x00-\x20\x7f]{1,4096}", "webhook_header_invalid")
        try:
            certificate = urlsplit(fields["cert_url"])
        except ValueError:
            raise PaymentError("webhook_header_invalid") from None
        if (fields["auth_algo"] != "SHA256withRSA" or certificate.scheme != "https" or
            certificate.netloc not in {"api.sandbox.paypal.com", API_HOST} or
            not certificate.path.startswith("/v1/notifications/certs/") or certificate.query or certificate.fragment):
            raise PaymentError("webhook_header_invalid")
        checked = self._api("POST", "/v1/notifications/verify-webhook-signature", {
            **fields, "webhook_id": self.config.webhook_id, "webhook_event": event,
        })
        if checked.get("verification_status") != "SUCCESS":
            raise PaymentError("webhook_signature_invalid")
        try:
            resource = event["resource"]
            if (event["event_type"] != "PAYMENT.CAPTURE.COMPLETED" or
                resource["supplementary_data"]["related_ids"]["order_id"] != intent.provider_reference):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise PaymentError("webhook_event_not_supported") from None
        # A fresh authenticated order read also verifies merchant/currency/amount.
        order_id = text(intent.provider_reference, r"[A-Z0-9]{8,32}", "order_id_invalid")
        data = self._api("GET", "/v2/checkout/orders/" + order_id)
        result = capture_evidence(data, intent, self.config.merchant_id)
        if result.event_id != "capture:" + str(resource.get("id")):
            raise PaymentError("webhook_capture_mismatch")
        return result
