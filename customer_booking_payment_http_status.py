"""Account-scoped payment status: safe unknown fallback, no browser authority."""
from __future__ import annotations
import customer_booking_payment_binding as binding
import customer_booking_payment_verified_reader as reader
import customer_booking_status_api as booking


def status(*, account_id: str, request_key: str) -> dict:
    reservation = booking.status(account_id=account_id, request_key=request_key)
    result = {'ok': True, 'bookingConfirmed': reservation['confirmed'],
              'payment': {'state': 'unverified', 'paid': False, 'environment': 'unknown'}}
    if reservation['confirmed'] is not True:
        return result
    associated = binding.lookup(account_id=account_id, request_key=request_key)
    if associated.get('bound') is not True:
        return result
    # A public status query must not infer amount or trust a browser-supplied
    # quote. The payment journal is consulted by the internal verified reader
    # only after a separate server-side authoritative price binding exists.
    result['payment']['state'] = 'bound_unverified'
    result['payment']['environment'] = 'sandbox'
    return result
