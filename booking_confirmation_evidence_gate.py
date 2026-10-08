"""Strict confirmation predicate; browser-provided flags are never evidence."""
from __future__ import annotations
from mercure_booking_identity_evidence import VerifiedBookingIdentity,validate_identity

def can_confirm(*, reference: str, account_id: str, vehicle_id: str,
                service: str, evidence: VerifiedBookingIdentity,
                calendar_verified: bool) -> bool:
    validate_identity(evidence,appointment_reference=reference,
                      account_id=account_id,vehicle_id=vehicle_id,service=service)
    return calendar_verified is True
