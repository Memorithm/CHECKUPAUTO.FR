"""Server-only composition. No public route or automatic write authorization."""
from __future__ import annotations

import customer_booking_server_execution
import customer_booking_payment_policy
import mercure_vl_provider_metadata_resolver


class CustomerBookingCompositionError(ValueError):
    pass


def execute(*, payload: dict, account: dict, vehicle: dict,
            line_id: str, operator_id: str, payment_policy: dict,
            payment_evidence: dict | None, authorized: bool = False,
            slot_evidence: dict | None = None):
    if authorized is not True:
        raise CustomerBookingCompositionError("booking_server_not_authorized")
    if not isinstance(payload,dict) or payload.get("service") not in {"technical","fitted"}:
        raise CustomerBookingCompositionError("booking_service_invalid")
    if slot_evidence is None:
        raise CustomerBookingCompositionError("booking_slot_evidence_required")
    if not isinstance(slot_evidence,dict) or slot_evidence.get("observed") is not True:
        raise CustomerBookingCompositionError("booking_slot_evidence_invalid")
    provider=mercure_vl_provider_metadata_resolver.resolve(
        service=payload["service"],line_id=line_id,operator_id=operator_id,
        date=payload.get("date"),time=payload.get("time"))
    fresh=provider.get("slot_evidence")
    if not isinstance(fresh,dict) or fresh.get("observed") is not True:
        raise CustomerBookingCompositionError("booking_fresh_slot_evidence_missing")
    if any(fresh.get(k)!=slot_evidence.get(k) for k in
           ("service","date","time","lineId","serviceId","duration","priceCents")):
        raise CustomerBookingCompositionError("booking_slot_evidence_changed")
    return customer_booking_server_execution.execute(
        payload=payload,account=account,vehicle=vehicle,
        metadata=provider["metadata"],observed_metadata=provider["observed_metadata"],
        service_label=provider["service_label"],server_authorized=True,
        payment_authorizer=customer_booking_payment_policy.authorize,
        payment_policy=payment_policy,payment_evidence=payment_evidence,
        slot_evidence=provider.get("slot_evidence"))
