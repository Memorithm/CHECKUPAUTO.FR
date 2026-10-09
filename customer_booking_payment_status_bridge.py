"""Account-scoped booking/payment presentation with no inferred settlement.

The booking journal contains no payment mode or payment reference. A verified
provider payment snapshot must be independently bound by an authorized server
caller; absent binding yields unknown, never paid.
"""
from __future__ import annotations
import customer_booking_status_api as booking
import customer_booking_payment_state as payment


def view(*, account_id: str, request_key: str,
         payment_policy: dict | None = None, provider_state: str | None = None,
         provider_verified: bool = False, booking_payment_bound: bool = False) -> dict:
    reservation = booking.status(account_id=account_id, request_key=request_key)
    result = {'booking': reservation, 'payment': {
        'mode': 'unknown', 'state': 'unverified', 'paid': False,
        'message': 'Statut du paiement non vérifié'}}
    if payment_policy is None:
        if provider_state is not None or provider_verified or booking_payment_bound:
            raise ValueError('payment_binding_missing')
        return result
    if booking_payment_bound is not True:
        raise ValueError('payment_booking_binding_unverified')
    result['payment'] = payment.assess(policy=payment_policy,
        provider_state=provider_state, provider_verified=provider_verified)
    return result
