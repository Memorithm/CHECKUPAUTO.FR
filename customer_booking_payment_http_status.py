"""Account-scoped payment status: safe unknown fallback, no browser authority."""
from __future__ import annotations
import customer_booking_payment_binding as binding
import customer_booking_payment_verified_reader as reader
import customer_booking_status_api as booking
import booking_bridge


def status(*, account_id: str, request_key: str) -> dict:
    reservation = booking.status(account_id=account_id, request_key=request_key)
    result = {'ok': True, 'bookingConfirmed': reservation['confirmed'],
              'payment': {'state': 'unverified', 'paid': False, 'environment': 'unknown'}}
    if reservation['confirmed'] is not True:
        return result
    associated = binding.lookup(account_id=account_id, request_key=request_key)
    if associated.get('bound') is not True:
        return result
    # An independent provider conversion must supply the exact authoritative
    # amount. No amount, provider status or receipt comes from the browser.
    try:
        basis = booking_bridge.authoritative_payment_basis(associated['providerBookingRef'])
        if (basis.get('bookingReference') != booking_bridge.booking_reference_for_external_id(associated['providerBookingRef'])
                or basis.get('provider') != booking_bridge.PROVIDER
                or basis.get('status') not in booking_bridge.CONFIRMED
                or type(basis.get('amountCents')) is not int):
            return result
        verified = reader.read(account_id=account_id, request_key=request_key,
                               expected_amount_cents=basis['amountCents'])
    except (KeyError, ValueError, TypeError, OSError):
        result['payment']['state'] = 'bound_unverified'
        result['payment']['environment'] = 'sandbox'
        return result
    result['payment']['environment'] = 'sandbox'
    result['payment']['state'] = verified['state']
    result['payment']['paid'] = (verified.get('paid') is True
        and verified.get('providerVerified') is True
        and verified.get('bookingPaymentBound') is True)
    return result
