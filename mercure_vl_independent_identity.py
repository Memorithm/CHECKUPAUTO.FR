"""Validate independently read provider identity before customer confirmation."""
from __future__ import annotations
from mercure_booking_identity_evidence import VerifiedBookingIdentity


def verify(*, record: dict, reference: str, account_id: str,
           vehicle_id: str, service: str) -> VerifiedBookingIdentity:
    if not isinstance(record,dict):
        raise ValueError("mercure_identity_record_invalid")
    expected={"reference":reference,"accountId":account_id,
              "vehicleId":vehicle_id,"service":service}
    if not all(isinstance(value,str) and value for value in expected.values()):
        raise ValueError("mercure_identity_context_invalid")
    if any(record.get(key)!=value for key,value in expected.items()):
        raise ValueError("mercure_identity_mismatch")
    if record.get("independentlyRead") is not True:
        raise ValueError("mercure_identity_not_independent")
    return VerifiedBookingIdentity(reference,account_id,vehicle_id,service,True)
