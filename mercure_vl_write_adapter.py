"""VL appointment writer with injected transport; never enabled by default.

The caller must durably claim idempotency before invoking create_once.
On timeout or ambiguous response, never replay without reconciliation.
"""
from __future__ import annotations

import re
from mercure_booking_write_contract import BookingWriteReceipt,MercureBookingWriteError
from mercure_vl_write_payload import build


class MercureVlWriteAdapter:
    def __init__(self, *, session, base_url: str, metadata: dict,
                 appointment: dict, authorized: bool = False):
        if authorized is not True:
            raise MercureBookingWriteError("mercure_customer_write_not_authorized")
        if not base_url.startswith("https://"):
            raise MercureBookingWriteError("mercure_write_https_required")
        if not callable(getattr(session,"post",None)):
            raise MercureBookingWriteError("mercure_write_transport_invalid")
        self.session=session
        self.base_url=base_url.rstrip("/")
        self.payload=build(appointment=appointment,**metadata)
        self._attempted=False

    def create_once(self, request):
        if self._attempted:
            raise MercureBookingWriteError("mercure_write_already_attempted")
        self._attempted=True
        try:
            response=self.session.post(
                self.base_url+"/admin/rendez_vous_add",
                data=self.payload,timeout=30,allow_redirects=False)
            if response.status_code!=200:
                raise MercureBookingWriteError("mercure_write_response_uncertain")
            data=response.json()
            reference=str((data or {}).get("id") or ((data or {}).get("event") or {}).get("id") or "")
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}",reference):
                raise MercureBookingWriteError("mercure_write_reference_uncertain")
            return BookingWriteReceipt(provider_reference=reference,accepted=True)
        except Exception as exc:
            raise MercureBookingWriteError("mercure_write_outcome_uncertain") from exc
