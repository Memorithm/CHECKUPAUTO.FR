"""Read-only, service-scoped Mercure policy for the requested online payment flow.

Payment-in-centre permission is NOT permission to silently downgrade an online
checkout. A policy observation is never a receipt or proof of a paid booking.
"""
from __future__ import annotations

import mercure_public_client as public


class MercurePaymentPolicyError(ValueError):
    pass


def qualify(*, service: str, response: object) -> dict:
    public.service(service)
    if (not isinstance(response, dict)
            or type(response.get("paiementCentre")) is not bool
            or type(response.get("paiementWeb")) is not bool):
        raise MercurePaymentPolicyError("booking_payment_policy_unverified")
    # CheckupAuto requires a verified external online payment. The Mercure
    # settlement flag is separate: centre-only Mercure does not mean the
    # CheckupAuto customer may pay at the centre.
    if not response["paiementWeb"] and not response["paiementCentre"]:
        raise MercurePaymentPolicyError("booking_no_payment_mode_available")
    settlement = "online" if response["paiementWeb"] else "centre"
    return {"service": service, "providerVerified": True, "paymentRequired": True,
            "source": "mercure-service-payment-options", "paymentMode": "online",
            "providerSettlementMode": settlement}


def load(*, service: str) -> dict:
    meta = public.service(service)
    session = public._provider_session()
    try:
        response = session.post(public.BASE + "/get_energie_prestation", data={
            "prestation": meta["id"], "type_centre": "1", "iframe": "false", "id": ""},
            timeout=20, allow_redirects=False)
        response.raise_for_status()
        if response.status_code != 200:
            raise MercurePaymentPolicyError("booking_payment_policy_unverified")
        return qualify(service=service, response=response.json())
    finally:
        session.close()
