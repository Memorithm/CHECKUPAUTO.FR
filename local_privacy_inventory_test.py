import unittest
from unittest import mock

import local_privacy_inventory as inventory


class LocalPrivacyInventoryTest(unittest.TestCase):
    def by_store(self, state):
        return {row["store"]: row for row in state["stores"]}

    def test_inventory_fails_closed_and_exposes_known_execution_gaps(self):
        state = inventory.snapshot()
        rows = self.by_store(state)

        self.assertTrue(state["inventoryComplete"])
        self.assertFalse(state["knownExecutionCoverageComplete"])
        self.assertEqual(state["scope"], "known-local-privacy-stores-v4")
        self.assertTrue(state["persistenceCatalog"]["complete"])
        self.assertEqual(state["persistenceCatalog"]["tableCount"], 79)
        self.assertTrue(state["persistenceCatalog"]["mappingComplete"])
        self.assertEqual(state["persistenceCatalog"]["subjectExecutionRequiredCount"],21)
        self.assertEqual(state["persistenceCatalog"]["executionGapCount"],9)
        self.assertFalse(state["persistenceCatalog"]["privacyExecutionCoverageAsserted"])
        self.assertIn(
            "persistence_catalog_complete_execution_coverage_incomplete",
            state["limitations"],
        )
        self.assertNotIn("inventory_scope_not_yet_exhaustive", state["limitations"])
        self.assertEqual(
            state["unresolvedStores"],
            ["booking_conversions","consent_receipts","notification_delivery","referral_accounts","referral_ledger","referral_rewards","referral_wallet_owner","review_followup","withdrawal_requests"],
        )
        self.assertEqual(state["unresolvedStoreCount"],9)
        self.assertEqual(rows["review_followup"]["executionState"], "partial_wired")
        self.assertEqual(rows["review_followup"]["adapter"], "privacy_suppression")
        self.assertEqual(
            rows["review_followup"]["bindingSource"],
            "mercure_rights.operationalInventory.appointments",
        )
        self.assertEqual(
            rows["review_followup"]["limitation"],
            "direct_mercure_subject_ref_only",
        )
        self.assertEqual(rows["booking_conversions"]["executionState"], "partial_wired")
        self.assertEqual(rows["booking_conversions"]["adapter"], "privacy_suppression")
        self.assertEqual(
            rows["booking_conversions"]["bindingSource"],
            "mercure_rights.operationalInventory.appointments",
        )
        self.assertEqual(
            rows["booking_conversions"]["prerequisite"],
            "mercure_provider_inventory_attested_and_complete",
        )
        self.assertIn(
            "browser_synthetic_unresolved",
            rows["booking_conversions"]["limitation"],
        )
        self.assertEqual(
            rows["booking_conversions"]["observability"],
            state["bookingConversionReconciliation"],
        )
        withdrawal = rows["withdrawal_requests"]
        self.assertEqual(withdrawal["executionState"], "partial_wired")
        self.assertEqual(withdrawal["adapter"], "withdrawal_evidence")
        self.assertEqual(
            withdrawal["bindingSource"],
            "withdrawal_requests.receipt_email_hash",
        )
        self.assertIn("retention_governed_erasure", withdrawal["limitation"])
        self.assertIn(
            "validated_retention_policy_for_erasure",
            withdrawal["prerequisite"],
        )
        self.assertIn(
            "withdrawal_subject_coverage_limited_to_exact_verified_receipt_email",
            state["limitations"],
        )

    def test_zero_local_booking_residuals_do_not_close_provider_backed_store(self):
        observed = {
            "available": True,
            "state": "clear",
            "unresolvedSyntheticRows": 0,
            "syntheticRowsWithoutAttribution": 0,
            "localResidualRows": 0,
            "providerIdInferenceUsed": False,
            "providerCoverageProven": False,
        }
        with mock.patch.object(
            inventory.booking_conversion_reconciliation,
            "status",
            return_value=observed,
        ):
            state = inventory.snapshot()

        row = self.by_store(state)["booking_conversions"]
        self.assertEqual(row["observability"]["state"], "clear")
        self.assertEqual(row["observability"]["localResidualRows"], 0)
        self.assertFalse(row["observability"]["providerCoverageProven"])
        self.assertEqual(row["executionState"], "partial_wired")
        self.assertIn("booking_conversions", state["unresolvedStores"])
        self.assertFalse(state["knownExecutionCoverageComplete"])
        self.assertIn(
            "local_booking_reconciliation_does_not_prove_provider_coverage",
            state["limitations"],
        )

    def test_residual_booking_counts_are_aggregate_only_and_remain_partial(self):
        observed = {
            "available": True,
            "state": "residual",
            "unresolvedSyntheticRows": 7,
            "syntheticRowsWithoutAttribution": 2,
            "localResidualRows": 9,
            "providerIdInferenceUsed": False,
            "providerCoverageProven": False,
        }
        with mock.patch.object(
            inventory.booking_conversion_reconciliation,
            "status",
            return_value=observed,
        ):
            state = inventory.snapshot()

        booking = state["bookingConversionReconciliation"]
        self.assertEqual(booking["unresolvedSyntheticRows"], 7)
        self.assertEqual(booking["syntheticRowsWithoutAttribution"], 2)
        self.assertEqual(booking["localResidualRows"], 9)
        self.assertFalse(booking["providerIdInferenceUsed"])
        self.assertFalse(booking["providerCoverageProven"])
        self.assertNotIn("externalId", repr(booking))
        self.assertNotIn("attributionToken", repr(booking))

    def test_analytics_is_not_given_an_invented_subject_erasure_path(self):
        state = inventory.snapshot()
        row = self.by_store(state)["analytics_event"]

        self.assertEqual(row["classification"], "not_subject_keyed")
        self.assertFalse(row["subjectErasureApplicable"])
        self.assertEqual(row["executionState"], "not_applicable")
        self.assertFalse(state["analyticsPrivacyProfile"]["subjectKeyed"])
        self.assertTrue(
            state["analyticsPrivacyProfile"]["obviousSubjectIdentifiersRedacted"]
        )

    def test_analytics_profile_change_fails_closed(self):
        profile = {
            "subjectKeyed": True,
            "clientIpStored": False,
            "cookieOrSessionStored": False,
            "queryStringStored": False,
            "obviousSubjectIdentifiersRedacted": True,
        }
        with mock.patch.object(inventory.analytics_store, "privacy_profile", return_value=profile):
            state = inventory.snapshot()

        row = self.by_store(state)["analytics_event"]
        self.assertTrue(row["subjectErasureApplicable"])
        self.assertEqual(row["executionState"], "unresolved")
        self.assertIn("analytics_event", state["unresolvedStores"])
        self.assertEqual(state["unresolvedStoreCount"], 10)

    def test_inventory_contains_no_subject_value_or_secret_material(self):
        serialized = repr(inventory.snapshot())
        self.assertNotIn("alice@example.test", serialized)
        self.assertNotIn("device-token", serialized)
        self.assertNotIn("api-key", serialized.lower())


if __name__ == "__main__":
    unittest.main()
