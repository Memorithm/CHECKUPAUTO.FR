"""Server-side sandbox payment status from persisted binding and verified journal.

No browser-supplied payment state or providerVerified flag is accepted.
Sandbox capture is deliberately not a production payment confirmation.
"""
from __future__ import annotations
import customer_booking_payment_status_bridge as bridge
import customer_booking_payment_verified_reader as verified


def view(*, account_id: str, request_key: str, expected_amount_cents: int,
         payment_policy: dict) -> dict:
    if not isinstance(payment_policy, dict) or payment_policy.get('providerVerified') is not True:
        raise ValueError('payment_policy_unverified')
    mode = payment_policy.get('paymentMode')
    if mode == 'centre':
        # The account-scoped booking status is always read by the bridge.
        result = bridge.view(account_id=account_id, request_key=request_key,
                             payment_policy=payment_policy, booking_payment_bound=True)
        result['environment'] = 'provider-centre'
        return result
    if mode != 'online':
        raise ValueError('payment_mode_invalid')
    evidence = verified.read(account_id=account_id, request_key=request_key,
                             expected_amount_cents=expected_amount_cents)
    state = evidence['state']
    if state not in {'captured', 'pending', 'created', 'authorized', 'declined', 'cancelled', 'error'}:
        raise ValueError('payment_state_invalid')
    if state == 'captured' and (evidence.get('paid') is not True or evidence.get('providerVerified') is not True):
        raise ValueError('payment_capture_unverified')
    result = bridge.view(account_id=account_id, request_key=request_key,
        payment_policy=payment_policy, booking_payment_bound=evidence.get('bookingPaymentBound') is True,
        provider_state='captured' if state == 'captured' else None,
        provider_verified=state == 'captured' and evidence.get('providerVerified') is True)
    result['environment'] = 'sandbox'
    result['payment']['providerState'] = state
    if state != 'captured':
        result['payment']['paid'] = False
    return result
