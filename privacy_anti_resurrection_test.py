import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import mobile_devices
import reminder_dispatch


class PrivacyAntiResurrectionTest(unittest.TestCase):
    def test_mobile_claim_is_blocked_for_erased_identity(self):
        with mock.patch.object(
            mobile_devices.privacy,
            "any_suppressed",
            return_value=True,
        ):
            with self.assertRaises(PermissionError):
                mobile_devices.issue_vehicle_claim("veh-1", "account", "42")

    def test_mercure_sync_does_not_recreate_suppressed_reminder_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_dir, old_db = reminder_dispatch.DATA_DIR, reminder_dispatch.DB
            reminder_dispatch.DATA_DIR = Path(tmp)
            reminder_dispatch.DB = Path(tmp) / "reminder.sqlite3"
            self.addCleanup(setattr, reminder_dispatch, "DATA_DIR", old_dir)
            self.addCleanup(setattr, reminder_dispatch, "DB", old_db)
            reminder_dispatch.init_db()
            rows = [{
                "vehicleId": "veh-1",
                "clientKind": "account",
                "clientId": "42",
                "dueDate": "2027-01-01",
                "appointmentId": "rdv-1",
            }]
            with mock.patch.object(
                reminder_dispatch.privacy,
                "any_suppressed",
                return_value=True,
            ):
                applied = reminder_dispatch._upsert(rows, "2026-09-21")
            self.assertEqual(applied, 0)
            with reminder_dispatch.connect() as db:
                count = db.execute("SELECT COUNT(*) n FROM reminder_target").fetchone()["n"]
            self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
