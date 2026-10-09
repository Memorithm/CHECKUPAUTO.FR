"""Safe customer booking confirmation presentation data."""
from __future__ import annotations
from customer_booking_status_api import status


def view(*, account_id: str, request_key: str) -> dict:
    result=status(account_id=account_id,request_key=request_key)
    if result["confirmed"] is not True:
        return {"confirmed":False,"message":"Rendez-vous en attente de vérification"}
    return {"confirmed":True,"message":"Rendez-vous confirmé"}
