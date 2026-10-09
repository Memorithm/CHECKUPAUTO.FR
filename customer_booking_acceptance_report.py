"""Generate a fail-closed homologation report from independently supplied evidence."""
from __future__ import annotations
import datetime as dt
from mercure_vl_acceptance_checklist import assess


def report(evidence: dict) -> dict:
    result=assess(evidence)
    return {
        "generatedAt":dt.datetime.now(dt.timezone.utc).isoformat(),
        "scope":"VL",
        "homologated":result["ready"],
        "missingEvidence":result["missing"],
        "productionActivated":False,
        "evidenceType":"explicit_external_verification",
    }
