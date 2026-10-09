"""Read-only payment state from account-bound sandbox journal evidence.

A locally captured state alone is not a receipt: a matching provider transaction
record, captured amount and provider reference are all required.
"""
from __future__ import annotations
import customer_booking_payment_binding as binding
import payment_checkout
from payment_core import PaymentError, SandboxJournal


class VerifiedPaymentReadError(ValueError):
    pass


def read(*, account_id: str, request_key: str, expected_amount_cents: int) -> dict:
    if type(expected_amount_cents) is not int or not 1 <= expected_amount_cents <= 9000:
        raise VerifiedPaymentReadError('payment_expected_amount_invalid')
    associated = binding.lookup(account_id=account_id, request_key=request_key)
    if associated.get('bound') is not True:
        raise VerifiedPaymentReadError('payment_booking_binding_missing')
    if associated.get('provider') != 'payline':
        raise VerifiedPaymentReadError('payment_provider_not_qualified')
    payment_ref = associated.get('paymentRef')
    if not isinstance(payment_ref, str) or len(payment_ref) != 32 or any(c not in '0123456789abcdef' for c in payment_ref):
        raise VerifiedPaymentReadError('payment_reference_invalid')
    try:
        journal = SandboxJournal(payment_checkout.journal_path())
        intent = journal.get(payment_ref)
    except (PaymentError, OSError, ValueError):
        raise VerifiedPaymentReadError('payment_intent_unavailable') from None
    if (intent.provider != 'payline' or intent.environment != 'sandbox'
            or intent.amount_cents != expected_amount_cents):
        raise VerifiedPaymentReadError('payment_intent_mismatch')
    if intent.state != 'captured':
        return {'state': intent.state, 'paid': False, 'providerVerified': False,
                'bookingPaymentBound': True, 'environment': 'sandbox'}
    if not intent.provider_reference:
        raise VerifiedPaymentReadError('payment_provider_reference_missing')
    try:
        transaction = journal.provider_transaction(payment_ref)
    except (PaymentError, OSError, ValueError):
        raise VerifiedPaymentReadError('payment_transaction_unverified') from None
    if (transaction.get('provider') != 'payline'
            or type(transaction.get('capturedAmountCents')) is not int
            or transaction['capturedAmountCents'] != expected_amount_cents
            or not transaction.get('transactionId')):
        raise VerifiedPaymentReadError('payment_capture_mismatch')
    return {'state': 'captured', 'paid': True, 'providerVerified': True,
            'bookingPaymentBound': True, 'environment': 'sandbox'}
