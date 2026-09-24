import unittest
from unittest import mock

import local_privacy_inventory as inventory


class LocalPrivacyInventoryTest(unittest.TestCase):
    def by_store(self, state):
        return {row["store"]: row for row in state["stores"]}

    def test_inventory_fails_closed_and_exposes_known_execution_gaps(self):
        state = inventory.snapshot()
        rows = self.by_store(state)

        self.assertFalse(state["inventoryComplete"])
        self.assertFalse(state["knownExecutionCoverageComplete"])
        self.assertEqual(
            set(state["unresolvedStores"]),
            {"review_followup", "booking_conversions"},
        )
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
        self.assertEqual(state["unresolvedStoreCount"], 3)

    def test_inventory_contains_no_subject_value_or_secret_material(self):
        serialized = repr(inventory.snapshot())
        self.assertNotIn("alice@example.test", serialized)
        self.assertNotIn("device-token", serialized)
        self.assertNotIn("api-key", serialized.lower())


if __name__ == "__main__":
    unittest.main()
