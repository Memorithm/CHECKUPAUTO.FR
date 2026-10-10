"""Resolve payment policy only from an account-owned confirmed Mercure booking.

No service or payment status is accepted from a browser. Failure to reconcile
provider booking identity with an independent conversion fails closed.
"""
from __future__ import annotations

import customer_booking_journal as journal
import booking_bridge
import mercure_vl_payment_policy_source as payment_source


def load(*, account_id: str, request_key: str) -> dict | None:
    booking = journal.status(account_id=account_id, key=request_key)
    if booking.get('confirmed') is not True:
        return None
    reference = booking.get('providerReference')
    if not isinstance(reference, str) or not reference:
        return None
    try:
        basis = booking_bridge.authoritative_payment_basis(reference)
        if (basis.get('provider') != booking_bridge.PROVIDER
                or basis.get('status') not in booking_bridge.CONFIRMED
                or basis.get('bookingReference') != booking_bridge.booking_reference_for_external_id(reference)):
            return None
        service = basis.get('service')
        if service not in ('technical', 'fitted'):
            return None
        policy = payment_source.load(service=service)
        if (not isinstance(policy, dict) or policy.get('service') != service
                or policy.get('providerVerified') is not True):
            return None
        return policy
    except (ValueError, KeyError, TypeError, OSError, RuntimeError):
        return None
