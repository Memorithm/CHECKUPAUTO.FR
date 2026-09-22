"""Monetico hosted-page sandbox adapter, wire version 3.0.

Protocol baseline: Euro Information technical documentation v2.0 (Feb 2025),
sections 1.4.2, 1.4.3, 9.3, 9.5, 9.8. Validate current merchant kit before live use.
Only the modern MAC covering all fields is accepted; no legacy fallback. Card
entry occurs on the bank's hosted page, never through our backend.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import html
import json
import re
from dataclasses import dataclass, field
from urllib.parse import parse_qsl
from zoneinfo import ZoneInfo

from payment_core import Intent, PaymentError, VerifiedEvent, decimal_amount, parse_eur, text
from payment_paypal import origin_url

SANDBOX_URL = "https://p.monetico-services.com/test/paiement.cgi"
MAX_BODY = 64 * 1024


@dataclass(frozen=True)
class MoneticoSandboxConfig:
    tpe: str
    societe: str
    key_hex: str = field(repr=False)
    return_origin: str

    def __post_init__(self):
        text(self.tpe, r"[A-Za-z0-9]{7}", "tpe_invalid")
        text(self.societe, r"[A-Za-z0-9_-]{1,64}", "societe_invalid")
        text(self.key_hex, r"[0-9A-Fa-f]{40}", "mac_key_invalid")
        origin_url(self.return_origin)


def canonical_fields(fields: dict[str, str]) -> bytes:
    if not isinstance(fields, dict) or not 1 <= len(fields) <= 128:
        raise PaymentError("monetico_fields_invalid")
    parts = []
    for name in sorted(fields):
        text(name, r"[A-Za-z0-9_-]{1,64}", "monetico_field_invalid")
        if name == "MAC":
            continue
        value = text(fields[name], r"[^\x00-\x1f\x7f]{0,16384}", "monetico_value_invalid")
        # A masked PAN may contain '*' but an embedded '*name=' would make
        # canonicalization ambiguous. Refuse rather than reinterpret it.
        if re.search(r"\*[A-Za-z0-9_-]+=", value):
            raise PaymentError("monetico_ambiguous_value")
        parts.append(name + "=" + value)
    raw = "*".join(parts).encode("utf-8")
    if len(raw) > MAX_BODY:
        raise PaymentError("monetico_fields_too_large")
    return raw


def mac(fields: dict[str, str], key_hex: str) -> str:
    text(key_hex, r"[0-9A-Fa-f]{40}", "mac_key_invalid")
    return hmac.new(bytes.fromhex(key_hex), canonical_fields(fields), hashlib.sha1).hexdigest()


def payment_form(intent: Intent, config: MoneticoSandboxConfig, billing: dict[str, str]) -> dict:
    if intent.provider != "monetico" or intent.environment != "sandbox":
        raise PaymentError("sandbox_monetico_required")
    if intent.provider_reference != intent.payment_id or intent.state not in {"created", "pending", "declined"}:
        raise PaymentError("bound_unpaid_monetico_intent_required")
    required = {"addressLine1", "city", "postalCode", "country"}
    optional = {"firstName", "lastName", "stateOrProvince"}
    if not isinstance(billing, dict) or not required <= set(billing) or set(billing) - required - optional:
        raise PaymentError("billing_fields_invalid")
    # Actual billing data is required: never fill in fictional customer data.
    safe_billing = {k: text(v, r"[^\x00-\x1f\x7f]{1,128}", "billing_value_invalid") for k, v in billing.items()}
    text(safe_billing["country"], r"[A-Z]{2}", "country_invalid")
    origin = origin_url(config.return_origin)
    fields = {
        "TPE": config.tpe, "version": "3.0", "societe": config.societe, "lgue": "FR",
        "date": dt.datetime.fromisoformat(intent.created_at).astimezone(ZoneInfo("Europe/Paris")).strftime("%d/%m/%Y:%H:%M:%S"),
        "montant": decimal_amount(intent.amount_cents) + "EUR", "reference": intent.payment_id,
        "contexte_commande": base64.b64encode(json.dumps({"billing": safe_billing}, ensure_ascii=False, separators=(",", ":")).encode()).decode(),
        "url_retour_ok": origin + "/payments/monetico/return",
        "url_retour_err": origin + "/payments/monetico/cancel",
    }
    fields["MAC"] = mac(fields, config.key_hex)
    # This deliberately returns a plan; it does not submit the form automatically.
    inputs = "".join('<input type="hidden" name="' + html.escape(k, quote=True) + '" value="' + html.escape(v, quote=True) + '">' for k, v in fields.items())
    form = ('<form method="post" accept-charset="UTF-8" action="' + SANDBOX_URL + '">' + inputs +
            '<button type="submit">Tester le paiement (aucun débit réel)</button></form>')
    return {"action": SANDBOX_URL, "fields": fields, "html": form, "environment": "sandbox"}


def verify_notification(raw: bytes, intent: Intent, config: MoneticoSandboxConfig) -> VerifiedEvent:
    if (intent.provider != "monetico" or intent.environment != "sandbox" or
        intent.provider_reference != intent.payment_id):
        raise PaymentError("bound_monetico_order_required")
    if not isinstance(raw, bytes) or len(raw) > MAX_BODY:
        raise PaymentError("notification_body_invalid")
    try:
        encoded = raw.decode("utf-8")
        if re.search(r"%(?![0-9A-Fa-f]{2})", encoded):
            raise ValueError
        pairs = parse_qsl(encoded, keep_blank_values=True, strict_parsing=True,
                          encoding="utf-8", errors="strict", max_num_fields=128)
        fields = {}
        for key, value in pairs:
            if key in fields:
                raise ValueError
            fields[key] = value
    except (ValueError, UnicodeError):
        raise PaymentError("notification_body_invalid") from None
    supplied = text(fields.get("MAC"), r"[0-9A-Fa-f]{40}", "notification_mac_invalid")
    if not hmac.compare_digest(supplied.lower(), mac(fields, config.key_hex)):
        raise PaymentError("notification_mac_invalid")
    # All callback fields, including unknown future fields, were authenticated.
    if (fields.get("TPE") != config.tpe or fields.get("reference") != intent.payment_id or
        fields.get("version", "3.0") != "3.0"):
        raise PaymentError("notification_binding_mismatch")
    amount = text(fields.get("montant"), r"[0-9]{1,5}(?:\.[0-9]{1,2})?EUR", "notification_amount_invalid")
    if parse_eur(amount[:-3]) != intent.amount_cents:
        raise PaymentError("notification_amount_mismatch")
    text(fields.get("date"), r"[0-9/:_a -]{10,40}", "notification_date_invalid")
    states = {"payetest": "authorized", "Annulation": "declined", "annulation": "declined", "attente_partenaire": "pending"}
    state = states.get(fields.get("code-retour"))
    if state is None:
        raise PaymentError("notification_code_not_supported")
    if state == "authorized":
        text(fields.get("numauto"), r"[A-Za-z0-9_-]{1,64}", "authorization_missing")
    # payetest confirms authorization, not captured/settled money. No raw fields,
    # masked PAN, payer IP, authentication data or billing details enter the ledger.
    event_id = hashlib.sha256(canonical_fields(fields)).hexdigest()
    return VerifiedEvent(intent.payment_id, "monetico", intent.payment_id, event_id, state, intent.amount_cents)


def acknowledgement(valid_mac: bool) -> bytes:
    if type(valid_mac) is not bool:
        raise PaymentError("boolean_required")
    return b"version=2\ncdr=0\n" if valid_mac else b"version=2\ncdr=1\n"
