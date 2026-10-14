"""Pre-Mercure, server-authoritative Payline quote for an authenticated customer.

This module does not start a payment, authorize a card, write a Mercure
appointment or claim that a slot is held. Call only from a CSRF-protected
authenticated backend; never pass a browser-supplied price or terms hash.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re

import analytics_store
import booking_bridge
import compliance_store
import customer_booking_api
import customer_booking_journal
import in_site_booking_routing
from payment_core import PaymentError, Quote


class PrepaymentQuoteError(ValueError):
    """Only stable codes; no identities, registration numbers or payment data."""


_FIELDS = frozenset({"service", "date", "time", "vehicleId", "requestKey"})
_KEY = re.compile(r"[A-Za-z0-9_-]{20,128}\Z")


def _browser_intent(ccid: str, *, now: dt.datetime | None = None) -> dict:
    if not isinstance(ccid, str) or not 1 <= len(ccid) <= 120:
        raise PrepaymentQuoteError("prepayment_browser_intent_invalid")
    with analytics_store.connect() as db:
        row = db.execute(
            "SELECT service,preferred_date,preferred_time,created_at "
            "FROM booking_intents WHERE token=?", (ccid,)
        ).fetchone()
    if row is None:
        raise PrepaymentQuoteError("prepayment_browser_intent_not_found")
    try:
        created = dt.datetime.fromisoformat(str(row["created_at"]).replace("Z", "+00:00"))
        current = now or dt.datetime.now(dt.timezone.utc)
        age = (current - created).total_seconds()
        if created.utcoffset() is None or not 0 <= age <= booking_bridge.BOOKING_BROWSER_TOKEN_TTL_HOURS * 3600:
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        raise PrepaymentQuoteError("prepayment_browser_intent_expired") from None
    return {
        "service": in_site_booking_routing.service_key(row["service"]),
        "date": str(row["preferred_date"] or ""),
        "time": str(row["preferred_time"] or ""),
    }


def reference_for(account_id: str, request_key: str) -> str:
    """Pseudonymous, deterministic order reference that cannot be mistaken for Mercure."""
    if not isinstance(account_id, str) or not 1 <= len(account_id) <= 128:
        raise PrepaymentQuoteError("prepayment_account_invalid")
    if not isinstance(request_key, str) or not _KEY.fullmatch(request_key):
        raise PrepaymentQuoteError("prepayment_key_invalid")
    data = json.dumps(
        ["checkupauto:premercure:v1", account_id, request_key],
        separators=(",", ":"), ensure_ascii=True,
    ).encode("ascii")
    return "checkupauto-pre:" + hashlib.sha256(data).hexdigest()


def prepare_quote(*, account: dict, payload: dict, ccid: str, cct: str,
                  now: dt.datetime | None = None) -> Quote:
    """Prepare one quote only after identity, token, CGV and live slot verification.

    The journal binds the request key to the exact request and customer, before
    any payment attempt. A second key or changed amount cannot reuse this quote.
    An existing reservation awaiting Mercure reconciliation is never reopened.
    """
    if not isinstance(account, dict) or not isinstance(payload, dict):
        raise PrepaymentQuoteError("prepayment_request_invalid")
    if set(payload) != _FIELDS or not all(isinstance(v, str) for v in payload.values()):
        raise PrepaymentQuoteError("prepayment_request_invalid")
    account_id = account.get("accountId")
    reference = reference_for(account_id, payload["requestKey"])
    if not isinstance(cct, str) or not booking_bridge.verify_browser_token(ccid, cct):
        raise PrepaymentQuoteError("prepayment_browser_token_invalid")

    source = _browser_intent(ccid, now=now)
    for field in ("service", "date", "time"):
        if not source[field] or source[field] != payload[field]:
            raise PrepaymentQuoteError("prepayment_browser_intent_mismatch")

    acceptance = compliance_store.checkout_acceptance_for_token(ccid)
    try:
        terms = booking_bridge.require_published_terms()
    except Exception:
        raise PrepaymentQuoteError("prepayment_terms_unavailable") from None
    if not isinstance(acceptance, dict) or acceptance.get("reviewed") is not True:
        raise PrepaymentQuoteError("prepayment_terms_not_accepted")
    if (acceptance.get("termsVersion") != terms.get("version")
            or acceptance.get("termsContentHash") != terms.get("contentHash")
            or not re.fullmatch(r"[0-9a-f]{64}", str(acceptance.get("termsContentHash") or ""))
            or acceptance.get("finalizedContractRef")):
        raise PrepaymentQuoteError("prepayment_terms_mismatch")
    if (booking_bridge._checkout_requirements(ccid)["requiresImmediatePerformance"]
            and acceptance.get("immediatePerformance") is not True):
        raise PrepaymentQuoteError("prepayment_immediate_performance_required")

    try:
        preflight = customer_booking_api.preflight(
            {k: payload[k] for k in ("service", "date", "time", "vehicleId")},
            account=account,
        )
    except customer_booking_api.BookingPreflightError as exc:
        raise PrepaymentQuoteError(str(exc)) from None
    if (preflight.get("bookingEnabled") is not True
            or preflight.get("slotAvailableAtCheck") is not True
            or preflight.get("slotHeld") is not False
            or preflight.get("service") != payload["service"]
            or preflight.get("date") != payload["date"]
            or preflight.get("time") != payload["time"]
            or preflight.get("vehicleId") != payload["vehicleId"]):
        raise PrepaymentQuoteError("prepayment_provider_not_qualified")

    try:
        quote = Quote(reference, payload["service"], preflight["priceCents"],
                      acceptance["termsContentHash"])
    except (KeyError, PaymentError, TypeError):
        raise PrepaymentQuoteError("prepayment_quote_invalid") from None

    # Hash-only persistent identity binding; no payment or provider write.
    try:
        state = customer_booking_journal.prepare(
            account_id=account_id, key=payload["requestKey"],
            request={k: payload[k] for k in sorted(_FIELDS - {"requestKey"})},
        )
    except customer_booking_journal.BookingJournalError as exc:
        raise PrepaymentQuoteError(str(exc)) from None
    if state.get("state") != "prepared":
        raise PrepaymentQuoteError("prepayment_booking_reconciliation_required")
    return quote
