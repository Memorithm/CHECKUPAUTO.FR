"""Internal-only booking orchestration; production writer remains disabled.

Only a qualified server-injected writer can create a provider appointment.
An ambiguous write never retries automatically.
"""
from __future__ import annotations

import customer_booking_journal as journal
import customer_booking_reconcile as reconciliation
from mercure_booking_write_contract import BookingWriteRequest, BookingWriter, writer as default_writer
from mercure_booking_write_validation import validate


class BookingCreationError(RuntimeError):
    pass


def create_and_verify(*, request: BookingWriteRequest, provider: BookingWriter | None = None) -> dict:
    request=validate(request)
    payload={
        "service":request.service,"date":request.date,"time":request.time,
        "vehicleId":request.vehicle_id,"priceCents":request.price_cents,
    }
    existing=journal.prepare(account_id=request.account_id,key=request.request_key,request=payload)
    if existing["state"]=="confirmed":
        return journal.status(account_id=request.account_id,key=request.request_key)
    if existing["state"]!="prepared":
        return {"state":"reconciliation_required","confirmed":False}
    # Persist the uncertain state BEFORE any external call. A process crash
    # therefore cannot create a second appointment on retry.
    journal.require_reconciliation(account_id=request.account_id,key=request.request_key)
    provider=provider if provider is not None else default_writer()
    try:
        receipt=provider.create_once(request)
    except Exception as exc:
        raise BookingCreationError("booking_provider_write_uncertain") from exc
    if receipt.accepted is not True or not receipt.provider_reference:
        return {"state":"reconciliation_required","confirmed":False}
    return reconciliation.reconcile(
        account_id=request.account_id,request_key=request.request_key,
        provider_reference=receipt.provider_reference,date=request.date,time=request.time)
