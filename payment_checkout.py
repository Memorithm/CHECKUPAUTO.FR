"""Trusted booking-to-payment bridge.

This module creates only internal sandbox intents. Price, service and contract
terms are resolved from server-side Mercure/compliance evidence; no browser
amount or service selection reaches payment_core. No provider call is made here.
"""
from __future__ import annotations

import os
from pathlib import Path

import booking_bridge as booking
import compliance_store as compliance
from payment_core import PaymentError, Quote, SandboxJournal


def journal_path() -> Path:
    return Path(os.environ.get("CYBERCHECK_DATA_DIR", "/root/CyberCheckData")) / "payments.sqlite3"


def quote_for_confirmed_booking(external_id: str) -> Quote:
    try:
        basis = booking.authoritative_payment_basis(external_id)
    except Exception:
        raise PaymentError("authoritative_booking_required") from None
    try:
        receipt = compliance.contract_acceptance_receipt(external_id)
    except Exception:
        raise PaymentError("contract_acceptance_unavailable") from None
    if not receipt:
        raise PaymentError("contract_acceptance_required")
    terms_hash = str(receipt.get("contentHash") or "").lower()
    if receipt.get("contractRef") != external_id or receipt.get("documentType") != "terms":
        raise PaymentError("contract_acceptance_mismatch")
    return Quote(
        basis["bookingReference"],
        basis["service"],
        int(basis["amountCents"]),
        terms_hash,
    )


def create_sandbox_intent(external_id: str, provider: str = "payline") -> dict:
    if provider != "payline":
        raise PaymentError("payline_sandbox_required")
    quote = quote_for_confirmed_booking(external_id)
    intent = SandboxJournal(journal_path()).create(quote, provider)
    return {
        "paymentId": intent.payment_id,
        "provider": intent.provider,
        "environment": intent.environment,
        "state": intent.state,
        "amountCents": intent.amount_cents,
        "currency": "EUR",
    }


def capability() -> dict:
    return {
        "environment": "sandbox",
        "authoritativeBookingBound": True,
        "contractAcceptanceBound": True,
        "serverAuthoritativePrice": True,
        "browserAmountAccepted": False,
        "browserServiceAccepted": False,
        "sandboxIntentCreationBound": True,
        "providerStartBound": False,
        "publicStartRouteBound": False,
        "livePaymentsEnabled": False,
    }
