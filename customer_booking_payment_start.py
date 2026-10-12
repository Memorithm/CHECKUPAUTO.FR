"""Payline checkout for an in-site booking already written to Mercure.

Order: Mercure appointment (journal confirmed after an independent read) ->
authoritative conversion and CGV receipt bound to the Mercure reference ->
Payline hosted payment -> return to ``/compte/reservation``. The browser only
supplies its CheckupAuto-signed intent token and the request key; service,
amount and booking reference come from server-side records.
"""
from __future__ import annotations

import booking_bridge as booking
import customer_booking_journal as journal
import customer_booking_payment_binding as binding
import customer_booking_payment_http_status as payment_status
import mercure_public_client
import payment_checkout
from payment_core import PaymentError


class BookingPaymentStartError(ValueError):
    pass


def _confirmed_reference(account_id: str, request_key: str) -> str:
    try:
        state = journal.status(account_id=account_id, key=request_key)
    except journal.BookingJournalError:
        raise BookingPaymentStartError("booking_not_found") from None
    reference = state.get("providerReference")
    if state.get("confirmed") is not True or not isinstance(reference, str) or not reference:
        raise BookingPaymentStartError("booking_not_confirmed")
    return reference


def record_confirmed_booking(*, account_id: str, request_key: str, ccid: str, cct: str,
                             service: str, price_cents: int) -> dict:
    """Record the Mercure booking as payable and bind the CGV receipt to it.

    ``service`` and ``price_cents`` must come from the server-side preflight
    that preceded the Mercure write, never from the browser.
    """
    if not booking.verify_browser_token(ccid, cct):
        raise BookingPaymentStartError("payment_browser_token_invalid")
    if service not in ("technical", "fitted"):
        raise BookingPaymentStartError("payment_basis_invalid")
    if type(price_cents) is not int or not 1 <= price_cents <= 9000:
        raise BookingPaymentStartError("payment_basis_invalid")
    reference = _confirmed_reference(account_id, request_key)
    result = booking.apply_conversion({
        "externalId": reference, "status": "confirmed", "ccid": ccid,
        "service": mercure_public_client.SERVICES[service]["label"],
        "amount": price_cents / 100,
    })
    return {"recorded": True, "contractAcceptanceBound": result.get("contractAcceptanceBound") is True}


def start(*, account_id: str, request_key: str, starter=None) -> dict:
    """Return the hosted Payline URL for this customer's confirmed booking."""
    reference = _confirmed_reference(account_id, request_key)
    current = payment_status.status(account_id=account_id, request_key=request_key)
    if current.get("payment", {}).get("paid") is True:
        return {"ok": True, "paid": True}
    try:
        started = payment_checkout.start_payline_for_booking(reference, starter=starter)
        binding.bind(account_id=account_id, request_key=request_key,
                     provider_booking_ref=reference, payment_ref=started["paymentId"],
                     payment_provider="payline", authorized=True)
    except (PaymentError, binding.BookingPaymentBindingError) as exc:
        raise BookingPaymentStartError(str(exc)) from None
    return {"ok": True, "paid": False, "redirectUrl": started["redirectUrl"],
            "amountCents": started["amountCents"]}
