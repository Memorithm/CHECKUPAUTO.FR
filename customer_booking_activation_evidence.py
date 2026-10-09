"""Fail-closed evidence gate for production booking activation."""
from __future__ import annotations

REQUIRED=("authenticated_customer","validated_vehicle","authoritative_slot",
          "provider_line_verified","provider_service_verified","provider_duration_verified",
          "writer_qualified","independent_identity_reader","idempotency_qualified",
          "payment_policy_verified","rollback_verified","monitoring_verified")


def assess(evidence: object) -> dict:
    if not isinstance(evidence,dict):
        raise ValueError("booking_activation_evidence_invalid")
    missing=[key for key in REQUIRED if evidence.get(key) is not True]
    return {"eligible":not missing,"missing":missing,"activated":False}
