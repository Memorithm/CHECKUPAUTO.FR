"""Adapter between the authenticated customer API and server-side Mercure composition.

No client-controlled provider metadata or payment evidence is accepted.
The caller must explicitly supply an authorized server context.
"""
from __future__ import annotations

import customer_booking_server_composition


class TrustedBookingContextError(ValueError):
    pass


def execute(*, payload, account, vehicle, metadata, observed_metadata,
            service_label, payment_policy, payment_evidence,
            server_authorized=False):
    if server_authorized is not True:
        raise TrustedBookingContextError("booking_server_not_authorized")
    if not isinstance(metadata,dict) or not isinstance(observed_metadata,dict):
        raise TrustedBookingContextError("booking_provider_context_invalid")
    required={"service_id","duration","centre_type","line_id","operator_id"}
    if set(metadata)!=required:
        raise TrustedBookingContextError("booking_provider_context_invalid")
    if not isinstance(service_label,str) or not service_label.strip():
        raise TrustedBookingContextError("booking_provider_context_invalid")
    return customer_booking_server_composition.execute(
        payload=payload,account=account,vehicle=vehicle,
        line_id=metadata["line_id"],operator_id=metadata["operator_id"],
        payment_policy=payment_policy,payment_evidence=payment_evidence,
        authorized=True)
