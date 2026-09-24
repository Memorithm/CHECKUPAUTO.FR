import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import analytics_store
import booking_bridge
import booking_conversion_erasure as privacy


class BookingConversionErasureTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.old_db = analytics_store.DB
        self.old_secret = booking_bridge.SECRET_FILE
        analytics_store.DB = root / "analytics.sqlite3"
        booking_bridge.SECRET_FILE = root / "mercure-webhook-secret"
        analytics_store.init_db()
        booking_bridge.init_db()

    def tearDown(self):
        analytics_store.DB = self.old_db
        booking_bridge.SECRET_FILE = self.old_secret
        self.tmp.cleanup()

    def seed(self, *external_ids):
        for external_id in external_ids:
            booking_bridge.apply_conversion({
                "externalId": external_id,
                "status": "confirmed",
                "appointmentDate": "2026-09-24T10:00",
                "service": "Contrôle technique",
                "amount": 80,
            })

    def remaining(self):
        with analytics_store.connect() as db:
            return [
                str(row["external_id"])
                for row in db.execute(
                    "SELECT external_id FROM booking_conversions ORDER BY external_id"
                ).fetchall()
            ]

    @staticmethod
    def complete_snapshot(*appointment_ids):
        return {
            "coverage": {"appointments": True},
            "operationalInventory": {
                "appointments": [
                    {"appointmentId": appointment_id} for appointment_id in appointment_ids
                ],
                "appointmentCountInWindow": len(appointment_ids),
            },
        }

    def test_complete_provider_inventory_erases_only_matching_rows(self):
        self.seed("apt-subject", "apt-other")
        with mock.patch.object(
            privacy.mercure_rights,
            "contact_snapshot",
            return_value=self.complete_snapshot("apt-subject"),
        ):
            result = privacy.erase_for_mercure_subject("request-1", "account:42")

        self.assertTrue(result["executed"])
        self.assertTrue(result["coverageComplete"])
        self.assertFalse(result["browserSyntheticCoverageComplete"])
        self.assertEqual(result["affectedRows"], 1)
        self.assertEqual(result["remainingActiveRows"], 0)
        self.assertEqual(self.remaining(), ["apt-other"])

        receipt = privacy.receipt("request-1")
        serialized = json.dumps(receipt, sort_keys=True)
        self.assertNotIn("apt-subject", serialized)
        self.assertEqual(receipt["appointmentCount"], 1)
        self.assertEqual(len(receipt["appointmentSetHash"]), 64)

    def test_incomplete_provider_inventory_causes_no_mutation(self):
        self.seed("apt-subject")
        with mock.patch.object(
            privacy.mercure_rights,
            "contact_snapshot",
            return_value={
                "coverage": {"appointments": False},
                "operationalInventory": {
                    "appointments": [{"appointmentId": "apt-subject"}],
                    "appointmentCountInWindow": 1,
                },
            },
        ):
            result = privacy.erase_for_mercure_subject("request-2", "account:42")

        self.assertFalse(result["executed"])
        self.assertFalse(result["coverageComplete"])
        self.assertEqual(result["reason"], "mercure_appointment_inventory_incomplete")
        self.assertEqual(self.remaining(), ["apt-subject"])
        self.assertIsNone(privacy.receipt("request-2"))

    def test_replay_removes_reintroduced_row_and_accumulates_proof(self):
        self.seed("apt-subject")
        snapshot = self.complete_snapshot("apt-subject")
        with mock.patch.object(privacy.mercure_rights, "contact_snapshot", return_value=snapshot):
            first = privacy.erase_for_mercure_subject("request-3", "free:42")
        self.assertEqual(first["affectedRows"], 1)
        self.assertEqual(self.remaining(), [])

        self.seed("apt-subject")
        with mock.patch.object(privacy.mercure_rights, "contact_snapshot", return_value=snapshot):
            second = privacy.erase_for_mercure_subject("request-3", "free:42")

        self.assertEqual(second["affectedRows"], 2)
        self.assertEqual(self.remaining(), [])
        self.assertEqual(privacy.receipt("request-3")["affectedRows"], 2)

    def test_empty_complete_inventory_records_verified_absence(self):
        with mock.patch.object(
            privacy.mercure_rights,
            "contact_snapshot",
            return_value=self.complete_snapshot(),
        ):
            result = privacy.erase_for_mercure_subject("request-4", "account:42")

        self.assertTrue(result["executed"])
        self.assertTrue(result["coverageComplete"])
        self.assertEqual(result["appointmentCount"], 0)
        self.assertEqual(result["affectedRows"], 0)
        self.assertIsNotNone(privacy.receipt("request-4"))

    def test_provider_inventory_count_mismatch_fails_before_deletion(self):
        self.seed("apt-subject")
        inconsistent = self.complete_snapshot("apt-subject")
        inconsistent["operationalInventory"]["appointmentCountInWindow"] = 2
        with mock.patch.object(
            privacy.mercure_rights,
            "contact_snapshot",
            return_value=inconsistent,
        ):
            with self.assertRaisesRegex(RuntimeError, "incohérent"):
                privacy.erase_for_mercure_subject("request-5", "account:42")

        self.assertEqual(self.remaining(), ["apt-subject"])
        self.assertIsNone(privacy.receipt("request-5"))

    def test_non_mercure_subject_reference_does_not_invent_linkage(self):
        self.seed("apt-subject")
        with mock.patch.object(privacy.mercure_rights, "contact_snapshot") as snapshot:
            result = privacy.erase_for_mercure_subject("request-6", "email:client@example.com")

        snapshot.assert_not_called()
        self.assertFalse(result["executed"])
        self.assertEqual(result["reason"], "mercure_subject_reference_required")
        self.assertEqual(self.remaining(), ["apt-subject"])

    def test_browser_synthetic_conversion_is_not_inferred_from_provider_inventory(self):
        self.seed("browser-opaque", "apt-subject")
        with mock.patch.object(
            privacy.mercure_rights,
            "contact_snapshot",
            return_value=self.complete_snapshot("apt-subject"),
        ):
            result = privacy.erase_for_mercure_subject("request-7", "account:42")

        self.assertEqual(self.remaining(), ["browser-opaque"])
        self.assertFalse(result["browserSyntheticCoverageComplete"])


if __name__ == "__main__":
    unittest.main()
