import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import review_followup
import review_followup_privacy as privacy


class ReviewFollowupPrivacyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name)
        self.db_path = self.data_dir / "review-followup.sqlite3"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.data_patch = mock.patch.object(review_followup, "DATA_DIR", self.data_dir)
        self.db_patch = mock.patch.object(review_followup, "DB", self.db_path)
        self.data_patch.start()
        self.db_patch.start()
        review_followup.init_db()

    def tearDown(self):
        self.db_patch.stop()
        self.data_patch.stop()
        self.tmp.cleanup()

    def seed(self, *appointment_ids):
        with review_followup.connect() as db:
            for appointment_id in appointment_ids:
                db.execute(
                    """INSERT INTO review_followup(
                         appointment_id,first_seen_at,last_attempt_at,sent_at,status,attempts,last_error
                       ) VALUES(?,?,?,?,?,?,?)""",
                    (appointment_id, "2026-09-24T00:00:00+00:00", "", "", "pending", 0, ""),
                )

    def remaining(self):
        with review_followup.connect() as db:
            return [
                str(row["appointment_id"])
                for row in db.execute(
                    "SELECT appointment_id FROM review_followup ORDER BY appointment_id"
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
        self.assertEqual(result["affectedRows"], 1)
        self.assertEqual(result["remainingActiveRows"], 0)
        self.assertEqual(self.remaining(), ["apt-other"])

        stored = privacy.receipt("request-1")
        self.assertIsNotNone(stored)
        self.assertEqual(stored["appointmentCount"], 1)
        serialized = json.dumps(stored, sort_keys=True)
        self.assertNotIn("apt-subject", serialized)
        self.assertRegex(stored["appointmentSetHash"], r"^[0-9a-f]{64}$")
        self.assertRegex(stored["evidenceHash"], r"^[0-9a-f]{64}$")

    def test_incomplete_provider_inventory_fails_closed_without_mutation(self):
        self.seed("apt-subject")
        snapshot = {
            "coverage": {"appointments": False},
            "operationalInventory": {
                "appointments": [{"appointmentId": "apt-subject"}],
                "appointmentCountInWindow": 1,
            },
        }
        with mock.patch.object(privacy.mercure_rights, "contact_snapshot", return_value=snapshot):
            result = privacy.erase_for_mercure_subject("request-2", "free:7")

        self.assertFalse(result["executed"])
        self.assertFalse(result["coverageComplete"])
        self.assertEqual(result["reason"], "mercure_appointment_inventory_incomplete")
        self.assertEqual(self.remaining(), ["apt-subject"])
        self.assertIsNone(privacy.receipt("request-2"))

    def test_replay_erases_reintroduced_row_and_accumulates_evidence(self):
        self.seed("apt-subject")
        snapshot = self.complete_snapshot("apt-subject")
        with mock.patch.object(privacy.mercure_rights, "contact_snapshot", return_value=snapshot):
            first = privacy.erase_for_mercure_subject("request-3", "account:42")
            self.seed("apt-subject")
            second = privacy.erase_for_mercure_subject("request-3", "account:42")

        self.assertEqual(first["affectedRows"], 1)
        self.assertEqual(second["affectedRows"], 2)
        self.assertEqual(second["remainingActiveRows"], 0)
        self.assertEqual(self.remaining(), [])
        self.assertEqual(privacy.receipt("request-3")["affectedRows"], 2)

    def test_complete_empty_inventory_records_verified_absence(self):
        with mock.patch.object(
            privacy.mercure_rights,
            "contact_snapshot",
            return_value=self.complete_snapshot(),
        ):
            result = privacy.erase_for_mercure_subject("request-4", "account:42")

        self.assertTrue(result["executed"])
        self.assertTrue(result["observed"])
        self.assertEqual(result["appointmentCount"], 0)
        self.assertEqual(result["affectedRows"], 0)
        self.assertIsNotNone(privacy.receipt("request-4"))

    def test_non_mercure_subject_does_not_invent_provider_linkage(self):
        self.seed("apt-subject")
        result = privacy.erase_for_mercure_subject("request-5", "person@example.test")

        self.assertFalse(result["executed"])
        self.assertFalse(result["coverageComplete"])
        self.assertEqual(result["reason"], "mercure_subject_reference_required")
        self.assertEqual(self.remaining(), ["apt-subject"])

    def test_provider_count_mismatch_fails_without_deletion(self):
        self.seed("apt-subject")
        snapshot = self.complete_snapshot("apt-subject")
        snapshot["operationalInventory"]["appointmentCountInWindow"] = 2
        with mock.patch.object(privacy.mercure_rights, "contact_snapshot", return_value=snapshot):
            with self.assertRaises(RuntimeError):
                privacy.erase_for_mercure_subject("request-6", "account:42")

        self.assertEqual(self.remaining(), ["apt-subject"])
        self.assertIsNone(privacy.receipt("request-6"))


if __name__ == "__main__":
    unittest.main()
