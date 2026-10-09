"""Customer booking E2E acceptance gate; does not create appointments."""
REQUIRED=("authenticated","billing_complete","vehicle_qualified","slot_verified",
          "provider_receipt","independent_identity","confirmation_displayed")

def evaluate(evidence):
    if not isinstance(evidence,dict):
        raise ValueError("booking_evidence_invalid")
    missing=[key for key in REQUIRED if evidence.get(key) is not True]
    return {"passed":not missing,"missing":missing,"liveTestPerformed":False}
