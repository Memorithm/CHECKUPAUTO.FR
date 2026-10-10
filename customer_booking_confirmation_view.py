"""Safe customer booking confirmation presentation data.

Never infer payment mode or capture from a confirmed Mercure appointment.
A separate account-scoped payment observation may provide the centre wording.
"""
from __future__ import annotations
from customer_booking_status_api import status


def view(*, account_id: str, request_key: str, payment_status: dict | None = None) -> dict:
    result=status(account_id=account_id,request_key=request_key)
    if result["confirmed"] is not True:
        return {"confirmed":False,"message":"Rendez-vous en attente de vérification",
                "paymentConfirmed":False}
    output={"confirmed":True,"message":"Rendez-vous confirmé",
            "paymentConfirmed":False,
            "paymentMessage":"Statut du paiement à vérifier séparément"}
    if (isinstance(payment_status,dict)
            and payment_status.get("providerVerified") is True
            and payment_status.get("paymentMode")=="centre"
            and payment_status.get("paymentRequired") is False
            and payment_status.get("service") in ("technical","fitted")):
        output["paymentMessage"]="Paiement à effectuer au centre le jour du rendez-vous"
    return output
