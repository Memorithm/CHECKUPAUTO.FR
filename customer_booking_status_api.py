"""Read-only booking status bound to the authenticated customer account."""
from __future__ import annotations
import re
import customer_booking_journal as journal


class BookingStatusError(ValueError):
    pass


def status(*, account_id: str, request_key: str) -> dict:
    if not isinstance(account_id,str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}",account_id):
        raise BookingStatusError("booking_account_invalid")
    if not isinstance(request_key,str) or not re.fullmatch(r"[A-Za-z0-9_-]{20,128}",request_key):
        raise BookingStatusError("booking_key_invalid")
    result=journal.status(account_id=account_id,key=request_key)
    if not isinstance(result,dict):
        raise BookingStatusError("booking_status_invalid")
    confirmed=result.get("state")=="confirmed" and result.get("confirmed") is True
    return {"ok":True,"state":result.get("state","unknown"),"confirmed":confirmed,
            "reconciliationRequired":result.get("state")=="reconciliation_required"}
