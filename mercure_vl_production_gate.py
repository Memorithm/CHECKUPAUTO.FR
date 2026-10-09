"""Production eligibility decision; no network write or deployment side effect."""
REQUIRED=("metadata_verified","customer_identity_verified","vehicle_verified",
          "slot_verified","writer_qualified","independent_read_qualified",
          "idempotency_verified","payment_policy_verified")

def assess(evidence):
    if not isinstance(evidence,dict):
        raise ValueError("mercure_production_evidence_invalid")
    missing=[key for key in REQUIRED if evidence.get(key) is not True]
    return {"eligible":not missing,"missing":missing,"activated":False}
