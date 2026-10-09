"""Executable acceptance checklist; no production deployment side effects."""
from __future__ import annotations

REQUIRED=("customer_auth","customer_billing","vehicle_vl","siv_fni_documents",
          "live_slot","provider_write","independent_calendar_read",
          "identity_binding","duplicate_recovery","customer_confirmation",
          "notification_policy","payment_policy","rollback")


def assess(evidence: dict) -> dict:
    if not isinstance(evidence,dict):
        raise ValueError("mercure_acceptance_evidence_invalid")
    missing=[key for key in REQUIRED if evidence.get(key) is not True]
    return {"ready":not missing,"missing":missing,"deployed":False}
