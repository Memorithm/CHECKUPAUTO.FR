"""Fail-closed production signoff checklist, independent of deployment settings."""
REQUIRED=("security_ci","customer_e2e","provider_identity","duplicate_recovery",
          "monitoring","rollback","notifications","payment_policy_verified")

def assess(evidence):
    if not isinstance(evidence,dict):
        raise ValueError("production_evidence_invalid")
    missing=[key for key in REQUIRED if evidence.get(key) is not True]
    return {"approved":not missing,"missing":missing,"productionActivated":False}
