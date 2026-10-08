"""Fail-closed identity evidence required before customer booking confirmation.

Provider identifiers must be independently mapped to CheckupAuto account and
vehicle identities. This function does not perform that mapping or any write.
"""
from __future__ import annotations

from dataclasses import dataclass


class BookingIdentityEvidenceError(ValueError):
    pass


@dataclass(frozen=True)
class VerifiedBookingIdentity:
    appointment_reference: str
    customer_account_id: str
    vehicle_id: str
    service: str
    provider_read_verified: bool


def validate_identity(evidence: VerifiedBookingIdentity, *, appointment_reference: str,
                      account_id: str, vehicle_id: str, service: str) -> bool:
    if not isinstance(evidence, VerifiedBookingIdentity):
        raise BookingIdentityEvidenceError("booking_identity_evidence_missing")
    if evidence.provider_read_verified is not True:
        raise BookingIdentityEvidenceError("booking_identity_not_verified")
    if not all(isinstance(value,str) and value for value in
               (appointment_reference,account_id,vehicle_id,service)):
        raise BookingIdentityEvidenceError("booking_identity_invalid")
    if (evidence.appointment_reference != appointment_reference
            or evidence.customer_account_id != account_id
            or evidence.vehicle_id != vehicle_id
            or evidence.service != service):
        raise BookingIdentityEvidenceError("booking_identity_mismatch")
    return True
