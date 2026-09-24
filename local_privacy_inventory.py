from __future__ import annotations

"""Fail-closed inventory of local persistence involved in data-subject rights.

This module is deliberately a technical inventory, not a legal classification.
It records only behaviours that are directly implemented in this repository.
`inventoryComplete` stays false until every local persistence surface has been
reviewed; callers must not infer completeness from the absence of a row here.
"""

import analytics_store


INVENTORY_SCOPE = "known-local-privacy-stores-v1"


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


def snapshot() -> dict:
    analytics = analytics_store.privacy_profile()
    analytics_subject_keyed = bool(analytics.get("subjectKeyed"))

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
            "review_followup_privacy",
            "provider_appointment_reference",
            "partial_wired",
            subject_erasure_applicable=True,
            adapter="privacy_suppression",
            binding_source="mercure_rights.operationalInventory.appointments",
            prerequisite="mercure_provider_inventory_attested_and_complete",
            limitation="direct_mercure_subject_ref_only",
        ),
        _row(
            "booking_conversions",
            "booking_bridge",
            "provider_appointment_reference_with_minimized_attribution",
            "conditional_unwired",
            subject_erasure_applicable=True,
            binding_source="mercure_rights.operationalInventory.appointments",
            prerequisite="mercure_provider_inventory_attested_and_complete",
            limitation="no_subject_complete_local_mutation_receipt",
        ),
    ]

    unresolved_states = {"unresolved", "conditional_unwired", "partial_wired"}
    unresolved = [row for row in stores if row["executionState"] in unresolved_states]
    return {
        "scope": INVENTORY_SCOPE,
        "inventoryComplete": False,
        "knownExecutionCoverageComplete": not unresolved,
        "knownStoreCount": len(stores),
        "unresolvedStoreCount": len(unresolved),
        "unresolvedStores": [row["store"] for row in unresolved],
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
        "limitations": [
            "inventory_scope_not_yet_exhaustive",
            "provider_reference_stores_require_attested_subject_appointment_inventory",
        ],
    }
