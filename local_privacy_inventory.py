from __future__ import annotations

"""Fail-closed inventory of local persistence involved in data-subject rights.

This module is deliberately a technical inventory, not a legal classification.
It records only behaviours that are directly implemented in this repository.
`inventoryComplete` means every production persistence surface has been discovered
and technically classified. It is deliberately independent from execution coverage;
callers must require `knownExecutionCoverageComplete` before treating rights coverage
as complete.
"""

import analytics_store
import booking_conversion_reconciliation
import local_persistence_catalog


INVENTORY_SCOPE = "known-local-privacy-stores-v4"


def _row(
    store: str,
    module: str,
    classification: str,
    execution_state: str,
    *,
    subject_erasure_applicable: bool,
    adapter: str = "",
    binding_source: str = "",
    prerequisite: str = "",
    limitation: str = "",
) -> dict:
    return {
        "store": store,
        "module": module,
        "classification": classification,
        "subjectErasureApplicable": bool(subject_erasure_applicable),
        "executionState": execution_state,
        "adapter": adapter,
        "bindingSource": binding_source,
        "prerequisite": prerequisite,
        "limitation": limitation,
    }


def _booking_observability(state: object) -> dict:
    """Normalize only aggregate, non-identifying booking reconciliation evidence."""
    row = state if isinstance(state, dict) else {}
    available = row.get("available") is True
    return {
        "available": available,
        "state": str(row.get("state") or ("unavailable" if not available else "")),
        "unresolvedSyntheticRows": max(0, int(row.get("unresolvedSyntheticRows") or 0)),
        "syntheticRowsWithoutAttribution": max(
            0, int(row.get("syntheticRowsWithoutAttribution") or 0)
        ),
        "localResidualRows": max(0, int(row.get("localResidualRows") or 0)),
        "providerIdInferenceUsed": row.get("providerIdInferenceUsed") is True,
        "providerCoverageProven": row.get("providerCoverageProven") is True,
    }


def snapshot() -> dict:
    persistence_catalog = local_persistence_catalog.snapshot()
    analytics = analytics_store.privacy_profile()
    analytics_subject_keyed = bool(analytics.get("subjectKeyed"))
    booking_observability = _booking_observability(
        booking_conversion_reconciliation.status()
    )

    booking_row = _row(
        "booking_conversions",
        "booking_conversion_erasure",
        "provider_appointment_reference_with_minimized_attribution",
        "partial_wired",
        subject_erasure_applicable=True,
        adapter="privacy_suppression",
        binding_source="mercure_rights.operationalInventory.appointments",
        prerequisite="mercure_provider_inventory_attested_and_complete",
        limitation="direct_mercure_subject_ref_and_provider_external_id_only_browser_synthetic_unresolved",
    )
    # This evidence is deliberately diagnostic only. Even when every currently
    # persisted browser placeholder has been reconciled, a zero local residual
    # count does not prove that Mercure exposed every provider-side appointment.
    booking_row["observability"] = booking_observability

    stores = [
        _row(
            "analytics_event",
            "analytics_store",
            "subject_keyed" if analytics_subject_keyed else "not_subject_keyed",
            "unresolved" if analytics_subject_keyed else "not_applicable",
            subject_erasure_applicable=analytics_subject_keyed,
            limitation=(
                "analytics_profile_reports_subject_keyed_data"
                if analytics_subject_keyed
                else ""
            ),
        ),
        _row(
            "marketing_consent",
            "marketing_consent",
            "subject_hash_state",
            "wired",
            subject_erasure_applicable=True,
            adapter="privacy_suppression",
        ),
        _row(
            "notification_privacy_binding",
            "notification_privacy",
            "subject_hash_to_recipient_binding",
            "wired",
            subject_erasure_applicable=True,
            adapter="privacy_suppression",
        ),
        _row(
            "reminder_target",
            "reminder_dispatch",
            "mercure_derived_subject_cache",
            "wired_for_supported_subject_kinds",
            subject_erasure_applicable=True,
            adapter="privacy_suppression",
            limitation="vehicle_mercure_account_mercure_free_only",
        ),
        _row(
            "mobile_installation_and_deadlines",
            "mobile_dsar_erasure",
            "installation_subject_store",
            "wired",
            subject_erasure_applicable=True,
            adapter="mobile_installation",
        ),
        _row(
            "referral_wallet",
            "referral_wallet_erasure",
            "financial_wallet_subject_store",
            "conditional",
            subject_erasure_applicable=True,
            adapter="referral_wallet",
            prerequisite="wallet_erasure_preconditions",
            limitation="financial_state_can_block_immediate_erasure",
        ),
        _row(
            "review_followup",
            "review_followup_rights",
            "provider_appointment_reference",
            "wired",
            subject_erasure_applicable=True,
            adapter="review_followup",
            binding_source="mercure_rights.operationalInventory.appointments",
            prerequisite="verified_mercure_subject_and_complete_provider_appointment_inventory",
            limitation="provider_inventory_required_at_execution",
        ),
        booking_row,
        _row(
            "withdrawal_requests",
            "withdrawal_rights",
            "direct_subject_and_contract_evidence",
            "partial_wired",
            subject_erasure_applicable=True,
            adapter="withdrawal_evidence",
            binding_source="withdrawal_requests.receipt_email_hash",
            prerequisite="exact_verified_receipt_email_subject_ref_and_validated_retention_policy_for_erasure",
            limitation="access_portability_and_retention_governed_erasure_email_only_historical_or_alternate_email_not_inferred",
        ),
    ]

    unresolved_states = {"unresolved", "conditional_unwired", "partial_wired"}
    unresolved = [row for row in stores if row["executionState"] in unresolved_states]
    catalog_complete = bool(persistence_catalog.get("complete"))
    mapping_complete = bool(persistence_catalog.get("mappingComplete"))
    catalog_gaps = {
        str(value)
        for value in persistence_catalog.get("executionGapTables") or []
        if str(value)
    }
    legacy_gaps = {str(row["store"]) for row in unresolved if str(row.get("store") or "")}
    combined_gaps = sorted(catalog_gaps | legacy_gaps)
    return {
        "scope": INVENTORY_SCOPE,
        "inventoryComplete": bool(catalog_complete and mapping_complete),
        "knownExecutionCoverageComplete": not combined_gaps,
        "persistenceCatalog": {
            "scope": str(persistence_catalog.get("scope") or ""),
            "complete": catalog_complete,
            "mappingComplete": mapping_complete,
            "tableCount": int(persistence_catalog.get("tableCount") or 0),
            "subjectExecutionRequiredCount": int(
                persistence_catalog.get("subjectExecutionRequiredCount") or 0
            ),
            "executionGapCount": int(persistence_catalog.get("executionGapCount") or 0),
            "state": str(persistence_catalog.get("state") or "unavailable"),
            "privacyExecutionCoverageAsserted": bool(
                persistence_catalog.get("privacyExecutionCoverageAsserted")
            ),
        },
        "knownStoreCount": len(stores),
        "unresolvedStoreCount": len(combined_gaps),
        "unresolvedStores": combined_gaps,
        "stores": stores,
        "analyticsPrivacyProfile": {
            "subjectKeyed": analytics_subject_keyed,
            "clientIpStored": bool(analytics.get("clientIpStored")),
            "cookieOrSessionStored": bool(analytics.get("cookieOrSessionStored")),
            "queryStringStored": bool(analytics.get("queryStringStored")),
            "obviousSubjectIdentifiersRedacted": bool(
                analytics.get("obviousSubjectIdentifiersRedacted")
            ),
        },
        "bookingConversionReconciliation": booking_observability,
        "limitations": [
            (
                "persistence_catalog_complete_execution_coverage_incomplete"
                if catalog_complete and mapping_complete and combined_gaps
                else (
                    "persistence_catalog_complete_execution_coverage_complete"
                    if catalog_complete and mapping_complete
                    else "persistence_catalog_incomplete"
                )
            ),
            "provider_reference_stores_require_attested_subject_appointment_inventory",
            "local_booking_reconciliation_does_not_prove_provider_coverage",
            "withdrawal_subject_coverage_limited_to_exact_verified_receipt_email",
        ],
    }
