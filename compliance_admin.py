from __future__ import annotations

from pathlib import Path

import compliance_operations
import compliance_register_attestation
import compliance_store
import data_subject_rights
import marketing_campaigns
import marketing_consent
import processing_risk_review
import retention_enforcement
import rights_completion_admin
import rights_readiness
import withdrawal_service


REGISTER_REVIEW_CONFIRMATION = "CURRENT-REGISTERS-REVIEWED"
PROCESSING_REVIEW_FIELDS = {
    "activityId",
    "expectedActivityHash",
    "securityStatus",
    "privacyStatus",
    "evidence",
}


def attest_operational_registers(
    payload: object,
    db_path: Path | str | None = None,
) -> dict:
    """Create a register-review attestation from an explicit admin action.

    This is the narrow application boundary intended for a future admin HTTP
    route. It accepts only the digest that was displayed to the operator and an
    explicit review confirmation. The underlying attestation primitive performs
    the final digest comparison so a register edit between display and submit
    fails closed.
    """
    if not isinstance(payload, dict) or set(payload) != {"confirm", "expectedRegisterHash"}:
        raise ValueError("payload d'attestation invalide")
    if str(payload.get("confirm") or "") != REGISTER_REVIEW_CONFIRMATION:
        raise PermissionError("confirmation de revue requise")
    expected_hash = str(payload.get("expectedRegisterHash") or "").strip().lower()
    state = compliance_register_attestation.attest(
        db_path,
        expected_register_hash=expected_hash,
    )
    return {
        "current": bool(state.get("current")),
        "stale": bool(state.get("stale")),
        "currentRegisterHash": str(state.get("currentRegisterHash") or ""),
        "attestedRegisterHash": str(state.get("attestedRegisterHash") or ""),
        "reviewedAt": str(state.get("reviewedAt") or ""),
        "evidenceHash": str(state.get("evidenceHash") or ""),
        "attestationCount": int(state.get("attestationCount") or 0),
    }


def review_high_risk_processing(
    payload: object,
    db_path: Path | str | None = None,
) -> dict:
    """Record one bounded security/privacy review from the admin trust boundary.

    The caller must submit the exact activity digest that was reviewed. Raw
    review evidence is forwarded to the core only long enough to derive its
    SHA-256 digest and is never reflected in the admin response.
    """
    if not isinstance(payload, dict) or set(payload) != PROCESSING_REVIEW_FIELDS:
        raise ValueError("payload de revue de traitement invalide")

    activity_id = str(payload.get("activityId") or "").strip()
    state = processing_risk_review.record_review(
        activity_id,
        expected_activity_hash=payload.get("expectedActivityHash"),
        security_status=payload.get("securityStatus"),
        privacy_status=payload.get("privacyStatus"),
        evidence=payload.get("evidence"),
        db_path=db_path,
    )
    row = next(
        (
            item
            for item in state.get("activities", [])
            if str(item.get("activityId") or "") == activity_id
        ),
        None,
    )
    if row is None:
        raise RuntimeError("preuve de revue de traitement indisponible")

    return {
        "activityId": str(row.get("activityId") or ""),
        "name": str(row.get("name") or ""),
        "currentActivityHash": str(row.get("currentActivityHash") or ""),
        "reviewedActivityHash": str(row.get("reviewedActivityHash") or ""),
        "securityStatus": str(row.get("securityStatus") or ""),
        "privacyStatus": str(row.get("privacyStatus") or ""),
        "stale": bool(row.get("stale")),
        "reviewedAt": str(row.get("reviewedAt") or ""),
        "sourceEvidenceHash": str(row.get("sourceEvidenceHash") or ""),
        "reviewEvidenceHash": str(row.get("reviewEvidenceHash") or ""),
    }


def rights_completion_snapshot(
    rights_requests: object,
    db_path: Path | str | None = None,
) -> dict:
    """Build bounded completion-plan state for all requests in admin snapshot.

    The admin boundary caps each database batch. Snapshot composition therefore
    chunks large request sets rather than silently dropping older requests.
    """
    rows = rights_requests if isinstance(rights_requests, list) else []
    request_ids: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        request_id = str(row.get("id") or "").strip()
        if not request_id or request_id in seen:
            continue
        seen.add(request_id)
        request_ids.append(request_id)

    plans: list[dict] = []
    batch_size = rights_completion_admin.MAX_REQUESTS
    for start in range(0, len(request_ids), batch_size):
        plans.extend(
            rights_completion_admin.statuses(
                request_ids[start : start + batch_size],
                db_path,
            )
        )
    return {
        "capability": rights_completion_admin.capability(),
        "requestCount": len(request_ids),
        "plans": plans,
    }


def snapshot(db_path: Path | str | None = None) -> dict:
    """Return the Compliance Center payload with operational-register evidence.

    The historical compliance store owns legal identity, published documents,
    rights requests, incidents and consent receipts. Operational GDPR registers
    are intentionally kept in their dedicated module but are surfaced through
    the same admin snapshot so the UI and activation gates have one source of
    truth.
    """
    result = compliance_store.admin_snapshot(db_path)
    withdrawal = withdrawal_service.status(db_path)
    operations = compliance_operations.snapshot(db_path)
    register_attestation = compliance_register_attestation.status(db_path)
    processing_reviews = processing_risk_review.status(db_path)
    rights_execution = rights_readiness.capability(db_path)
    rights_completion = rights_completion_snapshot(result.get("rightsRequests"), db_path)
    retention = retention_enforcement.status(db_path)
    marketing = marketing_consent.capability(db_path)
    campaigns = marketing_campaigns.capability(db_path)
    campaign_runs = marketing_campaigns.recent_runs(db_path, 100)
    operations_summary = dict(operations.get("summary") or {})
    blockers = list(operations_summary.get("blockers") or [])

    # An empty processing register is not evidence of operational readiness.
    # Fail closed until at least one active processing activity has been
    # documented and reviewed.
    if int(operations_summary.get("activeActivityCount") or 0) == 0:
        blockers.insert(
            0,
            {
                "type": "processing_register_missing",
                "id": "processing_activities",
                "name": "Registre des activités de traitement",
            },
        )

    # CheckupAuto has externally operated service boundaries (hosting and
    # integration channels). An empty processor/subprocessor inventory must not
    # be interpreted as evidence that this register has been completed. The
    # product therefore stays fail-closed until at least one active inventory
    # entry has been documented; legal classification and DPA status remain
    # operator-supplied facts, never inferred by the application.
    if int(operations_summary.get("activeProcessorCount") or 0) == 0:
        blockers.append(
            {
                "type": "processor_inventory_missing",
                "id": "processor_inventory",
                "name": "Inventaire des sous-traitants",
            }
        )

    # High-risk processing requires separate security and privacy reviews bound
    # to the exact activity content. A missing, non-approved or stale review is
    # an operational blocker independent of the DPIA status itself.
    blockers.extend(list(processing_reviews.get("blockers") or []))

    # Populated registers are not proof that a human review occurred. Readiness
    # therefore requires an attestation bound to the SHA-256 digest of the exact
    # current register content. Any subsequent substantive edit changes the
    # digest and automatically makes the previous review stale.
    if not bool(register_attestation.get("current")):
        blockers.append(
            {
                "type": (
                    "operational_register_attestation_stale"
                    if register_attestation.get("stale")
                    else "operational_register_attestation_missing"
                ),
                "id": "operational_register_attestation",
                "name": "Attestation de revue des registres opérationnels",
            }
        )

    operations_ready = not blockers
    operations_summary["blockers"] = blockers
    operations_summary["blockerCount"] = len(blockers)
    operations_summary["operationalRegistersReady"] = operations_ready
    operations_summary["processingRiskReviewsReady"] = bool(processing_reviews.get("ready"))
    operations_summary["processingRiskReviewBlockerCount"] = int(
        processing_reviews.get("blockerCount") or 0
    )
    operations["summary"] = operations_summary
    operations["processingRiskReview"] = processing_reviews

    summary = dict(result.get("summary") or {})
    summary["withdrawalFunctionBound"] = bool(withdrawal.get("bound"))
    summary["withdrawalPendingReceipts"] = int(withdrawal.get("pendingReceipts") or 0)
    summary["withdrawalManualMatchRequired"] = int(withdrawal.get("manualMatchRequired") or 0)
    # Phase-2 controls remain fail-closed. The rights engine can expose partial
    # executable coverage without pretending that every declared right and
    # every personal-data store is already bound.
    summary["dataSubjectExecutionBound"] = bool(rights_execution.get("bound"))
    summary["rightsCompletionGlobalCoverage"] = bool(
        rights_completion.get("capability", {}).get("globalCoverageComplete")
    )
    summary["retentionEnforcementBound"] = bool(retention.get("bound"))
    summary["retentionBlockerCount"] = int(retention.get("blockerCount") or 0)
    summary["marketingConsentBound"] = bool(marketing.get("bound"))
    summary["marketingCampaignsBound"] = bool(campaigns.get("bound"))
    summary["marketingCampaignRunCount"] = len(campaign_runs)
    summary["operationalRegistersReady"] = operations_ready
    summary["operationalBlockers"] = blockers
    summary["operationalRegisterAttestationCurrent"] = bool(register_attestation.get("current"))
    summary["processingRiskReviewsReady"] = bool(processing_reviews.get("ready"))

    # Recompute the public-contracting gate from explicit controls. The base
    # compliance store deliberately stayed closed until the executable
    # withdrawal function existed; this composed snapshot is now authoritative.
    legal_ready = bool(
        summary.get("identityComplete")
        and int(summary.get("publishedDocuments") or 0) == int(summary.get("requiredDocuments") or 0)
        and bool(summary.get("checkoutAcceptanceBound"))
        and bool(summary.get("withdrawalFunctionBound"))
        and bool(summary.get("dataSubjectExecutionBound"))
        and bool(summary.get("retentionEnforcementBound"))
        and int(summary.get("overdueRightsRequests") or 0) == 0
        and int(summary.get("overdueIncidentNotifications") or 0) == 0
    )
    summary["readyForPublicContracting"] = legal_ready and operations_ready
    result["summary"] = summary
    result["operations"] = operations
    result["operationalRegisterAttestation"] = register_attestation
    result["processingRiskReview"] = processing_reviews
    result["withdrawal"] = withdrawal
    result["dataSubjectExecution"] = rights_execution
    result["rightsCompletion"] = rights_completion
    result["rightsExecutionAudit"] = data_subject_rights.audit_rows(db_path, 200)
    result["marketingConsent"] = {
        "capability": marketing,
        "recent": marketing_consent.recent(db_path, 100),
    }
    result["marketingCampaigns"] = {
        "capability": campaigns,
        "recent": campaign_runs,
    }
    result["retention"] = retention
    return result
