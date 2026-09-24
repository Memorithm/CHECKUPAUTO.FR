"""Payline / Monext WebPayment sandbox transport.

Implements only the homologation SOAP WebPayment flow:
- doWebPayment -> token + hosted redirect URL
- getWebPaymentDetails -> authenticated final-state reread

No production endpoint, PAN/CVV collection, browser-trusted success path or public refund route exists here.
"""
from __future__ import annotations

import datetime as dt
import re
import ssl
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from urllib.parse import urlsplit

from payment_core import Intent, PaymentError, VerifiedEvent, cents
from payment_payline_config import PaylineSandboxConfig

API_VERSION = "34"
EUR_NUMERIC = "978"
SOAP_ENV = "http://schemas.xmlsoap.org/soap/envelope/"
IMPL_NS = "http://impl.ws.payline.experian.com"
OBJ_NS = "http://obj.ws.payline.experian.com"
MAX_RESPONSE_BYTES = 256 * 1024

ET.register_namespace("soapenv", SOAP_ENV)
ET.register_namespace("impl", IMPL_NS)
ET.register_namespace("obj", OBJ_NS)


@dataclass(frozen=True)
class RefundResult:
    result_code: str

    def __post_init__(self):
        if not re.fullmatch(r"[0-9]{5}", self.result_code):
            raise PaymentError("payline_refund_result_invalid")


@dataclass(frozen=True)
class StartResult:
    token: str
    redirect_url: str

    def __post_init__(self):
        _token(self.token)
        _redirect(self.redirect_url)


def _token(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value):
        raise PaymentError("payline_token_invalid")
    return value


def _redirect(value: object) -> str:
    if not isinstance(value, str) or len(value) > 2048 or not value.isascii():
        raise PaymentError("payline_redirect_invalid")
    try:
        u = urlsplit(value)
    except ValueError:
        raise PaymentError("payline_redirect_invalid") from None
    if u.scheme != "https" or not u.hostname or u.username or u.password or u.fragment:
        raise PaymentError("payline_redirect_invalid")
    host = u.hostname.lower()
    allowed = host in {"homologation-webpayment.payline.com", "homologation-payment.payline.com"}
    if not allowed:
        raise PaymentError("payline_redirect_invalid")
    return value


def _sub(parent: ET.Element, ns: str, name: str, text: object | None = None) -> ET.Element:
    node = ET.SubElement(parent, f"{{{ns}}}{name}")
    if text is not None:
        node.text = str(text)
    return node


def _soap(operation: str) -> tuple[ET.Element, ET.Element]:
    envelope = ET.Element(f"{{{SOAP_ENV}}}Envelope")
    _sub(envelope, SOAP_ENV, "Header")
    body = _sub(envelope, SOAP_ENV, "Body")
    request = _sub(body, IMPL_NS, operation)
    return envelope, request


def _urls(config: PaylineSandboxConfig, payment_id: str) -> tuple[str, str, str]:
    origin = config.public_origin
    payment_id = str(payment_id)
    if not re.fullmatch(r"[0-9a-f]{32}", payment_id):
        raise PaymentError("payment_id_invalid")
    state = "?paymentId=" + payment_id
    return (
        origin + "/payment/payline/return" + state,
        origin + "/payment/payline/cancel" + state,
        origin + "/api/payments/payline/notify",
    )


def do_web_payment_xml(intent: Intent, config: PaylineSandboxConfig) -> bytes:
    if not isinstance(intent, Intent) or intent.provider != "payline" or intent.environment != "sandbox":
        raise PaymentError("payline_intent_required")
    if not isinstance(config, PaylineSandboxConfig):
        raise PaymentError("payline_configuration_required")

    envelope, req = _soap("doWebPaymentRequest")
    _sub(req, IMPL_NS, "version", API_VERSION)

    payment = _sub(req, IMPL_NS, "payment")
    _sub(payment, OBJ_NS, "amount", cents(intent.amount_cents))
    _sub(payment, OBJ_NS, "currency", EUR_NUMERIC)
    _sub(payment, OBJ_NS, "action", "101")
    _sub(payment, OBJ_NS, "mode", "CPT")
    _sub(payment, OBJ_NS, "contractNumber", config.contract_number)

    return_url, cancel_url, notification_url = _urls(config, intent.payment_id)
    _sub(req, IMPL_NS, "returnURL", return_url)
    _sub(req, IMPL_NS, "cancelURL", cancel_url)

    order = _sub(req, IMPL_NS, "order")
    _sub(order, OBJ_NS, "ref", intent.payment_id)
    _sub(order, OBJ_NS, "amount", cents(intent.amount_cents))
    _sub(order, OBJ_NS, "currency", EUR_NUMERIC)
    _sub(order, OBJ_NS, "date", dt.datetime.now().strftime("%d/%m/%Y %H:%M"))

    _sub(req, IMPL_NS, "notificationURL", notification_url)

    selected = _sub(req, IMPL_NS, "selectedContractList")
    _sub(selected, OBJ_NS, "selectedContract", config.contract_number)

    buyer = _sub(req, IMPL_NS, "buyer")
    _sub(buyer, OBJ_NS, "customerId", intent.payment_id)

    _sub(req, IMPL_NS, "languageCode", "fr")
    _sub(req, IMPL_NS, "securityMode", "SSL")
    return ET.tostring(envelope, encoding="utf-8", xml_declaration=True)


def refund_xml(intent: Intent, transaction_id: str, amount_cents: int,
               config: PaylineSandboxConfig, sequence_number: str, comment: str = "") -> bytes:
    if not isinstance(intent, Intent) or intent.provider != "payline" or intent.environment != "sandbox":
        raise PaymentError("payline_intent_required")
    if intent.state != "captured":
        raise PaymentError("captured_payment_required")
    if not isinstance(config, PaylineSandboxConfig):
        raise PaymentError("payline_configuration_required")
    if not isinstance(transaction_id, str) or not re.fullmatch(r"[A-Za-z0-9:_-]{1,50}", transaction_id):
        raise PaymentError("payline_transaction_invalid")
    amount=cents(amount_cents)
    if amount > intent.amount_cents:
        raise PaymentError("refund_amount_exceeds_capture")
    if not isinstance(sequence_number,str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,50}",sequence_number):
        raise PaymentError("payline_refund_sequence_invalid")
    if not isinstance(comment,str) or len(comment)>255 or any(ord(ch)<32 and ch not in "\t" for ch in comment):
        raise PaymentError("payline_refund_comment_invalid")

    envelope, req = _soap("doRefundRequest")
    _sub(req, IMPL_NS, "version", API_VERSION)
    _sub(req, IMPL_NS, "transactionID", transaction_id)
    payment = _sub(req, IMPL_NS, "payment")
    _sub(payment, OBJ_NS, "amount", amount)
    _sub(payment, OBJ_NS, "currency", EUR_NUMERIC)
    _sub(payment, OBJ_NS, "action", "421")
    _sub(payment, OBJ_NS, "mode", "CPT")
    _sub(payment, OBJ_NS, "contractNumber", config.contract_number)
    if comment:
        _sub(req, IMPL_NS, "comment", comment)
    _sub(req, IMPL_NS, "sequenceNumber", sequence_number)
    return ET.tostring(envelope, encoding="utf-8", xml_declaration=True)


def get_details_xml(token: str) -> bytes:
    envelope, req = _soap("getWebPaymentDetailsRequest")
    _sub(req, IMPL_NS, "version", API_VERSION)
    _sub(req, IMPL_NS, "token", _token(token))
    return ET.tostring(envelope, encoding="utf-8", xml_declaration=True)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise PaymentError("payline_transport_redirect_refused")


def _post(config: PaylineSandboxConfig, body: bytes, soap_action: str, *, endpoint: str | None = None) -> bytes:
    if not isinstance(body, (bytes, bytearray)) or not body or len(body) > 128 * 1024:
        raise PaymentError("payline_request_invalid")
    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "Accept": "text/xml",
        "SOAPAction": soap_action,
        **config.authentication_headers(),
    }
    target = endpoint or config.webpayment_endpoint
    if target not in {config.webpayment_endpoint, config.directpayment_endpoint}:
        raise PaymentError("payline_endpoint_invalid")
    request = urllib.request.Request(target, data=bytes(body), headers=headers, method="POST")
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        _NoRedirect(),
    )
    try:
        with opener.open(request, timeout=30) as response:
            if response.status != 200:
                raise PaymentError("payline_transport_status")
            data = response.read(MAX_RESPONSE_BYTES + 1)
    except PaymentError:
        raise
    except urllib.error.HTTPError:
        raise PaymentError("payline_transport_status") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise PaymentError("payline_transport_unavailable") from None
    if len(data) > MAX_RESPONSE_BYTES:
        raise PaymentError("payline_response_too_large")
    return data


def _parse(xml: bytes) -> ET.Element:
    if not isinstance(xml, (bytes, bytearray)) or not xml or len(xml) > MAX_RESPONSE_BYTES:
        raise PaymentError("payline_response_invalid")
    upper = bytes(xml).upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise PaymentError("payline_response_invalid")
    try:
        return ET.fromstring(bytes(xml))
    except ET.ParseError:
        raise PaymentError("payline_response_invalid") from None


def _local(node: ET.Element, name: str) -> list[ET.Element]:
    return [item for item in node.iter() if item.tag.rsplit("}", 1)[-1] == name]


def _first(node: ET.Element, name: str, code: str) -> ET.Element:
    values = _local(node, name)
    if not values:
        raise PaymentError(code)
    return values[0]


def _one_text(node: ET.Element, name: str, code: str, *, required: bool = True) -> str:
    values = [str(item.text or "").strip() for item in _local(node, name)]
    values = [value for value in values if value]
    if not values:
        if required:
            raise PaymentError(code)
        return ""
    if len(set(values)) > 1:
        raise PaymentError(code)
    return values[0]


def _child_text(node: ET.Element, name: str, code: str, *, required: bool = True) -> str:
    values = []
    for item in list(node):
        if item.tag.rsplit("}", 1)[-1] == name:
            value = str(item.text or "").strip()
            if value:
                values.append(value)
    if not values:
        if required:
            raise PaymentError(code)
        return ""
    if len(set(values)) > 1:
        raise PaymentError(code)
    return values[0]


def parse_start_response(xml: bytes) -> StartResult:
    root = _parse(xml)
    result = _first(root, "result", "payline_result_missing")
    code = _child_text(result, "code", "payline_result_missing")
    if code != "00000":
        raise PaymentError("payline_start_refused")
    token = _one_text(root, "token", "payline_token_missing")
    redirect = _one_text(root, "redirectURL", "payline_redirect_missing")
    return StartResult(_token(token), _redirect(redirect))


def start(intent: Intent, config: PaylineSandboxConfig, *, sender=None) -> StartResult:
    sender = sender or (lambda body: _post(config, body, "doWebPayment"))
    return parse_start_response(sender(do_web_payment_xml(intent, config)))


def parse_details_response(xml: bytes, intent: Intent, token: str) -> VerifiedEvent:
    if intent.provider != "payline" or not intent.provider_reference:
        raise PaymentError("payline_bound_intent_required")
    if intent.provider_reference != _token(token):
        raise PaymentError("payline_token_binding_mismatch")
    root = _parse(xml)
    result = _first(root, "result", "payline_result_missing")
    code = _child_text(result, "code", "payline_result_missing")
    payment = _first(root, "payment", "payline_payment_missing")
    amount = _child_text(payment, "amount", "payline_amount_missing")
    currency = _child_text(payment, "currency", "payline_currency_missing")
    if amount != str(intent.amount_cents) or currency != EUR_NUMERIC:
        raise PaymentError("payline_amount_or_currency_mismatch")
    transaction = _first(root, "transaction", "payline_transaction_missing")
    transaction_id = _child_text(transaction, "id", "payline_transaction_missing")
    order = _first(root, "order", "payline_order_missing")
    order_ref = _child_text(order, "ref", "payline_order_reference_missing")
    if order_ref != intent.payment_id:
        raise PaymentError("payline_order_reference_mismatch")
    if not re.fullmatch(r"[A-Za-z0-9:_-]{1,50}", transaction_id):
        raise PaymentError("payline_transaction_invalid")

    if code == "00000":
        state = "captured"
    elif code.startswith("01") or code.startswith("04") or code in {"02319", "02302"}:
        state = "declined"
    elif code == "02005":
        state = "pending"
    else:
        raise PaymentError("payline_result_not_final")

    return VerifiedEvent(
        intent.payment_id,
        "payline",
        intent.provider_reference,
        "payline:" + transaction_id + ":" + code,
        state,
        intent.amount_cents,
        transaction_id,
    )


def refresh(intent: Intent, config: PaylineSandboxConfig, *, sender=None) -> VerifiedEvent:
    sender = sender or (lambda body: _post(config, body, "getWebPaymentDetails"))
    return parse_details_response(sender(get_details_xml(intent.provider_reference)), intent, intent.provider_reference)


def parse_refund_response(xml: bytes) -> RefundResult:
    root=_parse(xml)
    result=_first(root,"result","payline_result_missing")
    code=_child_text(result,"code","payline_result_missing")
    if code not in {"00000","02500"}:
        raise PaymentError("payline_refund_refused")
    return RefundResult(code)


def refund(intent: Intent, transaction_id: str, amount_cents: int,
           config: PaylineSandboxConfig, sequence_number: str,
           comment: str = "", *, sender=None) -> RefundResult:
    sender = sender or (
        lambda body: _post(
            config, body, "doRefund",
            endpoint=config.directpayment_endpoint,
        )
    )
    return parse_refund_response(
        sender(refund_xml(intent, transaction_id, amount_cents, config, sequence_number, comment))
    )


def capability() -> dict:
    return {
        "provider": "payline",
        "environment": "sandbox",
        "apiVersion": int(API_VERSION),
        "transportImplemented": True,
        "doWebPaymentImplemented": True,
        "getWebPaymentDetailsImplemented": True,
        "hostedPaymentPage": True,
        "panCollectedByCheckupAuto": False,
        "callbacksBound": True,
        "checkoutBound": True,
        "refundTransportImplemented": True,
        "refundsBound": False,
        "livePaymentsEnabled": False,
    }
