"""Customer-visible confirmation requires independent server-side booking evidence."""
from __future__ import annotations

REQUIRED=("authenticated","billing_complete","vehicle_qualified","slot_verified",
          "provider_receipt_persisted","provider_identity_verified",
          "calendar_verified","confirmation_visible")


def evaluate(evidence: dict) -> dict:
    if not isinstance(evidence,dict):
        raise ValueError("mercure_customer_journey_invalid")
    missing=[key for key in REQUIRED if evidence.get(key) is not True]
    return {"passed":not missing,"missing":missing,"realBookingPerformed":False}
