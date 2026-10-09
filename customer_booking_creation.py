"""Internal booking coordinator: one write, durable receipt, independent identity/read."""
from __future__ import annotations
import re
import customer_booking_journal as journal
import customer_booking_reconcile as reconciliation
from mercure_booking_write_contract import BookingWriteRequest,BookingWriteReceipt,BookingWriter
from mercure_booking_write_validation import validate

class BookingCreationError(RuntimeError):
    pass

def create_and_verify(*, request: BookingWriteRequest, provider: BookingWriter | None = None) -> dict:
    if provider is None or not callable(getattr(provider,"create_once",None)) or not callable(getattr(provider,"read_identity",None)):
        raise BookingCreationError("booking_provider_unqualified")
    request=validate(request)
    payload={"service":request.service,"date":request.date,"time":request.time,
             "vehicleId":request.vehicle_id,"priceCents":request.price_cents}
    existing=journal.prepare(account_id=request.account_id,key=request.request_key,request=payload)
    if existing["state"]=="confirmed":
        return journal.status(account_id=request.account_id,key=request.request_key)
    reference=journal.pending_provider_reference(account_id=request.account_id,key=request.request_key)
    if existing["state"]=="prepared":
        try:
            journal.require_reconciliation(account_id=request.account_id,key=request.request_key)
        except journal.BookingJournalError as exc:
            if str(exc)=="booking_reconciliation_required":
                return {"state":"reconciliation_required","confirmed":False}
            raise
        try:
            receipt=provider.create_once(request)
        except Exception as exc:
            raise BookingCreationError("booking_provider_write_uncertain") from exc
        if (not isinstance(receipt,BookingWriteReceipt) or receipt.accepted is not True
                or not isinstance(receipt.provider_reference,str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}",receipt.provider_reference)):
            return {"state":"reconciliation_required","confirmed":False}
        reference=receipt.provider_reference
        journal.record_provider_receipt(account_id=request.account_id,key=request.request_key,provider_reference=reference)
    if not reference:
        return {"state":"reconciliation_required","confirmed":False}
    try:
        proof=provider.read_identity(request,reference)
    except Exception as exc:
        raise BookingCreationError("booking_provider_identity_unavailable") from exc
    return reconciliation.reconcile_with_identity(
        account_id=request.account_id,request_key=request.request_key,
        provider_reference=reference,date=request.date,time=request.time,
        vehicle_id=request.vehicle_id,service=request.service,identity_evidence=proof)
