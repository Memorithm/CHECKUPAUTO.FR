"""Prepare a validated VL booking request from server-owned account data."""
from __future__ import annotations

from mercure_customer_booking_assembly import assemble
from mercure_vl_write_payload import build


def prepare(*, request, account, vehicle, metadata):
    assembled=assemble(request=request,account=account,vehicle=vehicle)
    if not isinstance(metadata,dict) or set(metadata)!={"service_id","duration","centre_type","line_id","operator_id"}:
        raise ValueError("mercure_vl_metadata_missing")
    payload=build(appointment=assembled["appointment"],**metadata)
    return {"payload":payload,"customerWriteQualified":False,
            "providerWritePerformed":False,"bookingConfirmed":False}
