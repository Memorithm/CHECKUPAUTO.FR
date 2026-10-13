"""Server-only booking create gate; never enables an unqualified Mercure writer."""
from __future__ import annotations
import re

import customer_booking_api
import in_site_booking_readiness


class BookingCreateInvalid(ValueError):
    pass


class BookingCreateUnavailable(RuntimeError):
    pass


def create(payload: object, *, account: dict, executor=None, trusted_context=None) -> dict:
    if not isinstance(payload,dict) or set(payload)!={"service","date","time","vehicleId","requestKey"}:
        raise BookingCreateInvalid("booking_create_request_invalid")
    key=payload.get("requestKey")
    if not isinstance(key,str) or not re.fullmatch(r"[A-Za-z0-9_-]{20,128}",key):
        raise BookingCreateInvalid("booking_create_key_invalid")
    try:
        preflight=customer_booking_api.preflight(
            {name:payload[name] for name in ("service","date","time","vehicleId")},
            account=account)
    except customer_booking_api.BookingPreflightError as exc:
        raise BookingCreateInvalid(str(exc)) from exc
    if preflight.get("bookingEnabled") is not True or in_site_booking_readiness.public_status().get("bookingEnabled") is not True:
        raise BookingCreateUnavailable("booking_writer_not_qualified")
    # Explicit fail-closed boundary until an authorized server-only provider
    # is wired and its evidence has passed production homologation.
    if not callable(executor) or not isinstance(trusted_context,dict):
        raise BookingCreateUnavailable("booking_writer_not_connected")
    required={"metadata","observed_metadata","service_label","payment_policy","payment_evidence","slot_evidence"}
    if set(trusted_context)!=required:
        raise BookingCreateUnavailable("booking_provider_context_unqualified")
    vehicles=account.get("vehicles")
    if not isinstance(vehicles,list):
        raise BookingCreateInvalid("booking_vehicle_not_owned")
    matches=[item for item in vehicles if isinstance(item,dict)
             and item.get("vehicleId")==payload["vehicleId"]]
    if len(matches)!=1:
        raise BookingCreateInvalid("booking_vehicle_not_owned")
    # The provider's settlement mode is independent of CheckupAuto prepayment.
    # Never run a real booking writer on browser-supplied or absent payment proof.
    policy=trusted_context["payment_policy"]
    evidence=trusted_context["payment_evidence"]
    if (not isinstance(policy,dict) or policy.get("providerVerified") is not True
            or policy.get("paymentRequired") is not True
            or policy.get("paymentMode") != "online"
            or not isinstance(evidence,dict)
            or evidence.get("providerVerified") is not True
            or evidence.get("paid") is not True):
        raise BookingCreateUnavailable("booking_verified_prepayment_required")
    result=executor(payload=payload,account=account,vehicle=matches[0],
                    **trusted_context,server_authorized=True)
    if not isinstance(result,dict) or result.get("confirmed") is not True:
        return {"ok":True,"confirmed":False,"state":"reconciliation_required"}
    return {"ok":True,"confirmed":True,"state":"confirmed",
            "paymentDue":"none","paymentConfirmed":True,
            "service":preflight.get("service"),"priceCents":preflight.get("priceCents")}
