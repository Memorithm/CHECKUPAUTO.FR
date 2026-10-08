"""Server-side booking reconciliation using independent Mercure calendar evidence.

This internal function must not be exposed as a public browser confirmation API.
It performs no provider writes or payment actions.
"""
from __future__ import annotations

import customer_booking_journal as journal
import mercure_booking_evidence as evidence
from mercure_booking_identity_evidence import VerifiedBookingIdentity, validate_identity


class BookingReconciliationError(RuntimeError):
    pass


def reconcile(*, account_id: str, request_key: str, provider_reference: str,
              date: str, time: str, vehicle_id: str = '', service: str = '',
              identity_evidence: VerifiedBookingIdentity | None = None) -> dict:
    # Require an existing account-scoped claim before contacting Mercure.
    state=journal.status(account_id=account_id,key=request_key)
    # Identity proof is mandatory even for an already-confirmed journal entry.
    # Callers must obtain this evidence from an independent trusted provider read.
    validate_identity(identity_evidence,appointment_reference=provider_reference,
                      account_id=account_id,vehicle_id=vehicle_id,service=service)
    if state["state"] == "confirmed":
        if state["providerReference"] != provider_reference:
            raise BookingReconciliationError("booking_provider_reference_conflict")
        return {"confirmed":True,"state":"confirmed","providerReference":provider_reference}
    if state["state"] != "reconciliation_required":
        raise BookingReconciliationError("booking_reconciliation_required")
    try:
        verified=evidence.verify_appointment(
            provider_reference=provider_reference,date=date,time=time)
    except evidence.MercureBookingEvidenceError as exc:
        raise BookingReconciliationError("booking_provider_evidence_unavailable") from exc
    if verified is not True:
        return {"confirmed":False,"state":"reconciliation_required"}
    return journal.confirm_verified(
        account_id=account_id,key=request_key,
        provider_reference=provider_reference,verified=True)
