#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import compliance_admin
import compliance_operations
import compliance_register_attestation
import compliance_store
import local_privacy_inventory
import retention_enforcement

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _terms_evidence(db_path: Path | str | None = None) -> dict:
    terms = compliance_store.published_document("terms", db_path)
    receipts = [
        row
        for row in compliance_store.consent_receipts(db_path, 500)
        if row.get("purpose") == "contract_terms"
        and row.get("documentType") == "terms"
        and row.get("source") == "mercure_contract_confirmation"
    ]
    version = str((terms or {}).get("version") or "")
    content_hash = str((terms or {}).get("contentHash") or "").lower()
    matching = [
        row
        for row in receipts
        if str(row.get("documentVersion") or "") == version
        and str(row.get("contentHash") or "").lower() == content_hash
    ]
    immediate = sum(1 for row in receipts if row.get("immediatePerformance") is True)
    return {
        "publishedTermsPresent": bool(terms),
        "publishedTermsVersion": version,
        "publishedTermsContentHash": content_hash if _SHA256.fullmatch(content_hash) else "",
        "mercureContractReceiptCount": len(receipts),
        "matchingPublishedTermsReceiptCount": len(matching),
        "allMercureContractReceiptsMatchPublishedTerms": bool(receipts) and len(matching) == len(receipts),
        "immediatePerformanceReceiptCount": immediate,
        "rawContractReferencesExposed": False,
    }


def snapshot(db_path: Path | str | None = None) -> dict:
    state = compliance_admin.snapshot(db_path)
    summary = dict(state.get("summary") or {})
    operations = dict((state.get("operations") or {}).get("summary") or {})
    attestation = compliance_register_attestation.status(db_path)
    retention = retention_enforcement.status(db_path)
    local = local_privacy_inventory.snapshot()
    processors = compliance_operations.processors(db_path)
    activities = compliance_operations.processing_activities(db_path)
    register_hash = str(attestation.get("currentRegisterHash") or "").lower()

    return {
        "schema": "checkupauto.compliance-147-bounded-snapshot/v1",
        "identity": {
            "complete": bool(summary.get("identityComplete")),
            "missingFields": sorted(str(x) for x in summary.get("missingIdentityFields") or []),
        },
        "legalDocuments": {
            "published": int(summary.get("publishedDocuments") or 0),
            "required": int(summary.get("requiredDocuments") or 0),
            "missing": sorted(str(x) for x in summary.get("missingDocuments") or []),
        },
        "termsEvidence": _terms_evidence(db_path),
        "operations": {
            "activityIds": sorted(str(x.get("id") or "") for x in activities if str(x.get("id") or "")),
            "processorIds": sorted(str(x.get("id") or "") for x in processors if str(x.get("id") or "")),
            "processorDpaStates": {
                str(x.get("id") or ""): str(x.get("dpaStatus") or "")
                for x in processors
                if str(x.get("id") or "")
            },
            "activeActivityCount": int(operations.get("activeActivityCount") or 0),
            "activeProcessorCount": int(operations.get("activeProcessorCount") or 0),
            "blockerTypes": sorted({
                str(x.get("type") or "")
                for x in summary.get("operationalBlockers") or []
                if isinstance(x, dict) and str(x.get("type") or "")
            }),
            "processingRiskReviewsReady": bool(summary.get("processingRiskReviewsReady")),
        },
        "registerAttestation": {
            "current": bool(attestation.get("current")),
            "stale": bool(attestation.get("stale")),
            "attestationCount": int(attestation.get("attestationCount") or 0),
            "currentRegisterHash": register_hash if _SHA256.fullmatch(register_hash) else "",
            "attestedRegisterHash": (
                str(attestation.get("attestedRegisterHash") or "").lower()
                if _SHA256.fullmatch(str(attestation.get("attestedRegisterHash") or "").lower())
                else ""
            ),
            "reviewedAtPresent": bool(str(attestation.get("reviewedAt") or "")),
        },
        "retention": {
            "bound": bool(retention.get("bound")),
            "readyRuleCount": int(retention.get("readyRuleCount") or 0),
            "ruleCount": int(retention.get("ruleCount") or 0),
            "blockers": [
                {
                    "ruleId": str(x.get("ruleId") or ""),
                    "reason": str(x.get("reason") or ""),
                }
                for x in retention.get("blockers") or []
                if isinstance(x, dict)
            ],
            "policies": [
                {
                    "id": str(x.get("id") or ""),
                    "ready": bool(x.get("ready")),
                    "configured": bool(x.get("configured")),
                    "enabled": bool(x.get("enabled")),
                    "legalReviewRequired": bool(x.get("legalReviewRequired")),
                    "activeDays": int(x["activeDays"]) if isinstance(x.get("activeDays"), int) else None,
                    "blocker": str(x.get("blocker") or ""),
                }
                for x in retention.get("policies") or []
                if isinstance(x, dict)
            ],
        },
        "rights": {
            "dataSubjectExecutionBound": bool(summary.get("dataSubjectExecutionBound")),
            "globalCoverageComplete": bool(summary.get("rightsCompletionGlobalCoverage")),
            "overdueRequests": int(summary.get("overdueRightsRequests") or 0),
        },
        "incidents": {
            "overdueNotifications": int(summary.get("overdueIncidentNotifications") or 0),
        },
        "mercure": {
            "providerCoverageAttested": bool(summary.get("mercureProviderCoverageAttested")),
            "providerCoverageState": str(summary.get("mercureProviderCoverageState") or ""),
            "rectificationState": str(summary.get("mercureRectificationState") or ""),
            "rectificationProviderAttested": bool(summary.get("mercureRectificationProviderAttested")),
        },
        "localPrivacy": {
            "scope": str(local.get("scope") or ""),
            "inventoryComplete": bool(local.get("inventoryComplete")),
            "knownExecutionCoverageComplete": bool(local.get("knownExecutionCoverageComplete")),
            "unresolvedStoreCount": int(local.get("unresolvedStoreCount") or 0),
            "unresolvedStores": sorted(str(x) for x in local.get("unresolvedStores") or []),
        },
        "phase2": {
            "ready": bool(summary.get("phase2CoverageReady")),
            "blockers": list(summary.get("phase2Blockers") or []),
        },
        "readyForPublicContracting": bool(summary.get("readyForPublicContracting")),
        "personalDataExposed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db")
    args = parser.parse_args()
    state = snapshot(Path(args.db) if args.db else None)
    print(json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
