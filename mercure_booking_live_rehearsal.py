"""Operator-only live rehearsal. Never invoked by customer routes or CI.

Requires explicit opt-in and uses the existing synthetic booking test identity.
Always attempts cleanup after a successful creation. Does not enable real
customer reservations or payment.
"""
from __future__ import annotations

import os
import sys

import booking_test


def rehearse(service: str, date: str, time: str) -> dict:
    if os.environ.get("CHECKUPAUTO_LIVE_BOOKING_REHEARSAL") != "I_ACCEPT_TEMPORARY_MERCURE_APPOINTMENT":
        raise PermissionError("live_rehearsal_not_authorized")
    session=booking_test.create_session()
    token=session["token"]
    created=None
    try:
        created=booking_test.create_appointment(token,service,date,time)
        if created.get("providerVerified") is not True:
            raise RuntimeError("mercure_creation_not_verified")
        return {"createdAndReread":True,"cleanupRequired":True}
    finally:
        if created is not None:
            removed=booking_test.remove_appointment(token)
            if removed.get("providerVerified") is not True:
                raise RuntimeError("mercure_cleanup_not_verified")


if __name__=="__main__":
    if len(sys.argv)!=4:
        raise SystemExit("usage: mercure_booking_live_rehearsal.py SERVICE YYYY-MM-DD HH:MM")
    try:
        result=rehearse(*sys.argv[1:])
    except Exception:
        print("MERCURE_REHEARSAL_FAILED_OR_CLEANUP_UNCERTAIN")
        raise SystemExit(1)
    print("MERCURE_REHEARSAL_CREATE_READ_DELETE_VERIFIED")
