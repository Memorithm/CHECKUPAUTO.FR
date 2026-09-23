from __future__ import annotations

import datetime
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import reminder_dispatch as reminders


class ReminderCachedPrivacyRecheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_dir, self.old_db = reminders.DATA_DIR, reminders.DB
        reminders.DATA_DIR = Path(self.tmp.name)
        reminders.DB = Path(self.tmp.name) / "reminder.sqlite3"
        reminders.init_db()
        self.row = {
            "vehicleId": "veh-cached-1",
            "clientKind": "account",
            "clientId": "42",
            "dueDate": "2026-10-01",
            "appointmentId": "rdv-cached-1",
        }
        with mock.patch.object(reminders.privacy, "any_suppressed", return_value=False):
            self.assertEqual(reminders._upsert([self.row], "2026-09-23"), 1)

    def tearDown(self):
        reminders.DATA_DIR, reminders.DB = self.old_dir, self.old_db
        self.tmp.cleanup()

    def test_cached_target_is_removed_from_eligibility_after_restriction(self):
        now = datetime.datetime(2026, 9, 24, 12, 0, tzinfo=datetime.timezone.utc)
        with mock.patch.object(reminders.privacy, "any_suppressed", return_value=True) as suppressed:
            eligible = reminders._eligible(now)

        self.assertEqual(eligible, [])
        candidates, purpose = suppressed.call_args.args
        self.assertEqual(purpose, "all_processing")
        self.assertIn(("vehicle", "veh-cached-1"), candidates)
        self.assertIn(("mercure_account", "42"), candidates)

    def test_cached_restriction_blocks_permanent_recipient_lookup(self):
        reference_row = {
            "vehicle_id": "veh-cached-1",
            "client_kind": "account",
            "client_id": "42",
            "due_date": "2026-10-01",
            "appointment_id": "rdv-cached-1",
            "days_before": 7,
        }
        reference = reminders._reference(reference_row)
        context = {
            "incidentId": "incident-1",
            "channel": "email",
            "category": "ct_due_reminder",
            "permanentState": "open",
            "reference": reference,
        }
        with mock.patch.object(
            reminders.notifications, "permanent_failure_context", return_value=context
        ), mock.patch.object(
            reminders.privacy, "any_suppressed", return_value=True
        ), mock.patch.object(reminders.mercure, "customer_email") as customer_email:
            with self.assertRaises(LookupError):
                reminders.permanent_recipient_check("incident-1")

        customer_email.assert_not_called()

    def test_marketing_only_suppression_does_not_block_operational_reminder(self):
        now = datetime.datetime(2026, 9, 24, 12, 0, tzinfo=datetime.timezone.utc)

        def only_marketing(_candidates, purpose):
            return purpose == "direct_marketing_email"

        with mock.patch.object(reminders.privacy, "any_suppressed", side_effect=only_marketing):
            eligible = reminders._eligible(now)

        self.assertEqual(len(eligible), 1)
        self.assertEqual(eligible[0]["vehicle_id"], "veh-cached-1")
        self.assertEqual(eligible[0]["days_before"], 7)


if __name__ == "__main__":
    unittest.main()
