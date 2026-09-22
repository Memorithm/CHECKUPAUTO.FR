from __future__ import annotations

from pathlib import Path

import compliance_operations
import compliance_store
import data_subject_rights
import marketing_campaigns
import marketing_consent
import retention_enforcement
import rights_readiness
import withdrawal_service


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
    rights_execution = rights_readiness.capability(db_path)
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

    operations_ready = not blockers
    operations_summary["blockers"] = blockers
    operations_summary["blockerCount"] = len(blockers)
    operations_summary["operationalRegistersReady"] = operations_ready
    operations["summary"] = operations_summary

    summary = dict(result.get("summary") or {})
    summary["withdrawalFunctionBound"] = bool(withdrawal.get("bound"))
    summary["withdrawalPendingReceipts"] = int(withdrawal.get("pendingReceipts") or 0)
    summary["withdrawalManualMatchRequired"] = int(withdrawal.get("manualMatchRequired") or 0)
    # Phase-2 controls remain fail-closed. The rights engine can expose partial
    # executable coverage without pretending that every declared right and
    # every personal-data store is already bound.
    summary["dataSubjectExecutionBound"] = bool(rights_execution.get("bound"))
    summary["retentionEnforcementBound"] = bool(retention.get("bound"))
    summary["retentionBlockerCount"] = int(retention.get("blockerCount") or 0)
    summary["marketingConsentBound"] = bool(marketing.get("bound"))
    summary["marketingCampaignsBound"] = bool(campaigns.get("bound"))
    summary["marketingCampaignRunCount"] = len(campaign_runs)
    summary["operationalRegistersReady"] = operations_ready
    summary["operationalBlockers"] = blockers

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
    result["withdrawal"] = withdrawal
    result["dataSubjectExecution"] = rights_execution
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
