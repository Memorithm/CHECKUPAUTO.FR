import tempfile
import unittest
from pathlib import Path

import mobile_authoritative_sync as sync
import mobile_devices as devices
import reminder_dispatch as reminders


class MobileAuthoritativeSyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.old_device_dir, self.old_device_db = devices.DATA_DIR, devices.DB
        self.old_reminder_dir, self.old_reminder_db = reminders.DATA_DIR, reminders.DB
        devices.DATA_DIR = root
        devices.DB = root / "mobile.sqlite3"
        reminders.DATA_DIR = root
        reminders.DB = root / "reminders.sqlite3"
        devices.init_db()
        reminders.init_db()
        self.installation = "60cf7ccf-4297-41f4-b76b-c0bd44dbe3d1"
        self.secret = "A" * 43
        devices.register({
            "installationId": self.installation,
            "registrationSecret": self.secret,
            "deviceToken": "ab" * 32,
            "environment": "sandbox",
        })

    def tearDown(self):
        devices.DATA_DIR, devices.DB = self.old_device_dir, self.old_device_db
        reminders.DATA_DIR, reminders.DB = self.old_reminder_dir, self.old_reminder_db
        self.tmp.cleanup()

    def bind(self):
        claim = devices.issue_vehicle_claim("vehicle-77", "account", "client-42")
        return devices.consume_vehicle_claim({
            "installationId": self.installation,
            "registrationSecret": self.secret,
            "claimToken": claim["claimToken"],
        })

    def test_binding_imports_verified_inventory_as_authoritative_deadline(self):
        fallback_id = "e62c0b27-2141-4f5c-b2f4-1e458aa6a6ca"
        devices.sync_deadlines({
            "installationId": self.installation,
            "registrationSecret": self.secret,
            "deadlines": [{"deadlineId": fallback_id, "dueDate": "2027-01-15"}],
        })
        binding = self.bind()
        reminders._upsert([{
            "vehicleId": "vehicle-77",
            "clientKind": "account",
            "clientId": "client-42",
            "dueDate": "2027-02-15",
            "appointmentId": "77",
        }])

        result = sync.sync_installation(self.installation)
        self.assertEqual(result["authoritativeDeadlines"], 1)
        targets = devices.due_targets("2027-01-01", "2027-03-01")
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0]["deadline_id"], binding["bindingId"])
        self.assertEqual(targets[0]["due_date"], "2027-02-15")
        self.assertEqual(targets[0]["source"], devices.AUTHORITATIVE_DEADLINE_SOURCE)

    def test_missing_inventory_removes_authoritative_snapshot_and_restores_fallback(self):
        fallback_id = "e62c0b27-2141-4f5c-b2f4-1e458aa6a6ca"
        devices.sync_deadlines({
            "installationId": self.installation,
            "registrationSecret": self.secret,
            "deadlines": [{"deadlineId": fallback_id, "dueDate": "2027-01-15"}],
        })
        self.bind()
        reminders._upsert([{
            "vehicleId": "vehicle-77",
            "clientKind": "account",
            "clientId": "client-42",
            "dueDate": "2027-02-15",
            "appointmentId": "77",
        }])
        sync.sync_installation(self.installation)
        with reminders.connect() as db:
            db.execute("DELETE FROM reminder_target WHERE vehicle_id=?", ("vehicle-77",))
        result = sync.sync_installation(self.installation)
        self.assertEqual(result["authoritativeDeadlines"], 0)
        targets = devices.due_targets("2027-01-01", "2027-03-01")
        self.assertEqual([(row["deadline_id"], row["source"]) for row in targets], [
            (fallback_id, devices.DEVICE_DEADLINE_SOURCE),
        ])

    def test_sync_once_is_noop_without_bindings(self):
        result = sync.sync_once()
        self.assertTrue(result["ok"])
        self.assertEqual(result["installations"], 0)


if __name__ == "__main__":
    unittest.main()
