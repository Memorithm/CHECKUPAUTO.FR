from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import reminder_dispatch as reminders


class ReminderPrimitivePrivacyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_dir, self.old_db = reminders.DATA_DIR, reminders.DB
        reminders.DATA_DIR = Path(self.tmp.name)
        reminders.DB = Path(self.tmp.name) / "reminder.sqlite3"
        reminders.init_db()
        self.row = {
            "vehicleId": "veh-primitive-privacy",
            "clientKind": "account",
            "clientId": "42",
            "dueDate": "2099-10-01",
            "appointmentId": "rdv-primitive-privacy",
        }
        with mock.patch.object(reminders.privacy, "any_suppressed", return_value=False):
            self.assertEqual(reminders._upsert([self.row], "2099-09-23"), 1)

    def tearDown(self):
        reminders.DATA_DIR, reminders.DB = self.old_dir, self.old_db
        self.tmp.cleanup()

    def test_direct_claim_target_fails_closed_after_restriction(self):
        with mock.patch.object(reminders.privacy, "any_suppressed", return_value=True) as suppressed:
            with self.assertRaises(LookupError):
                reminders.mobile_claim_target("veh-primitive-privacy")

        candidates, purpose = suppressed.call_args.args
        self.assertEqual(purpose, "all_processing")
        self.assertIn(("vehicle", "veh-primitive-privacy"), candidates)
        self.assertIn(("mercure_account", "42"), candidates)

    def test_direct_candidate_list_hides_restricted_cached_target(self):
        with mock.patch.object(reminders.privacy, "any_suppressed", return_value=True):
            self.assertEqual(reminders.mobile_claim_candidates(30), [])

    def test_direct_deadline_read_hides_restricted_cached_target(self):
        with mock.patch.object(reminders.privacy, "any_suppressed", return_value=True):
            self.assertEqual(
                reminders.deadlines_for_vehicle_ids(["veh-primitive-privacy"]),
                [],
            )

    def test_marketing_only_suppression_keeps_operational_reads_available(self):
        def only_marketing(_candidates, purpose):
            return purpose == "direct_marketing_email"

        with mock.patch.object(reminders.privacy, "any_suppressed", side_effect=only_marketing):
            target = reminders.mobile_claim_target("veh-primitive-privacy")
            candidates = reminders.mobile_claim_candidates(30)
            deadlines = reminders.deadlines_for_vehicle_ids(["veh-primitive-privacy"])

        self.assertEqual(target["vehicle_id"], "veh-primitive-privacy")
        self.assertEqual([row["vehicle_id"] for row in candidates], ["veh-primitive-privacy"])
        self.assertEqual(
            deadlines,
            [{"vehicle_id": "veh-primitive-privacy", "due_date": "2099-10-01"}],
        )


if __name__ == "__main__":
    unittest.main()
