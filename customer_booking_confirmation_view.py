"""Safe customer booking confirmation presentation data.

A confirmed Mercure appointment is not evidence that the customer has paid.
The confirmation page must not claim a card capture or a paid balance.
"""
from __future__ import annotations
from customer_booking_status_api import status


def view(*, account_id: str, request_key: str) -> dict:
    result=status(account_id=account_id,request_key=request_key)
    if result["confirmed"] is not True:
        return {"confirmed":False,"message":"Rendez-vous en attente de vérification",
                "paymentConfirmed":False}
    return {"confirmed":True,"message":"Rendez-vous confirmé",
            "paymentConfirmed":False,
            "paymentMessage":"Paiement à effectuer au centre le jour du rendez-vous"}
