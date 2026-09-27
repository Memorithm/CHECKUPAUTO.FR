import tempfile
import unittest
from pathlib import Path
from unittest import mock

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

    def test_binding_syncs_authoritative_deadline_before_apns_permission(self):
        second_installation = "936246c1-8932-4b6f-92b6-1ea591c09f96"
        second_secret = "B" * 43
        devices.register_installation({
            "installationId": second_installation,
            "registrationSecret": second_secret,
        })
        claim = devices.issue_vehicle_claim("vehicle-88", "account", "client-88")
        binding = devices.consume_vehicle_claim({
            "installationId": second_installation,
            "registrationSecret": second_secret,
            "claimToken": claim["claimToken"],
        })
        reminders._upsert([{
            "vehicleId": "vehicle-88",
            "clientKind": "account",
            "clientId": "client-88",
            "dueDate": "2027-04-30",
            "appointmentId": "88",
        }])
        result = sync.sync_installation(second_installation)
        self.assertEqual(result["authoritativeDeadlines"], 1)
        inventory = devices.bound_inventory({
            "installationId": second_installation,
            "registrationSecret": second_secret,
        })
        self.assertEqual(inventory["vehicles"], [{
            "bindingId": binding["bindingId"],
            "dueDate": "2027-04-30",
            "appointmentAt": None,
        }])


    def test_future_appointment_is_projected_only_on_exact_bound_identity(self):
        binding = self.bind()
        reminders._upsert([{
            "vehicleId": "vehicle-77",
            "clientKind": "account",
            "clientId": "client-42",
            "dueDate": "2027-02-15",
            "appointmentId": "historic-77",
        }])
        upcoming = [
            {
                "vehicleId": "vehicle-77",
                "clientKind": "account",
                "clientId": "other-client",
                "appointmentId": "wrong",
                "appointmentAt": "2099-10-04T13:00:00+02:00",
            },
            {
                "vehicleId": "vehicle-77",
                "clientKind": "account",
                "clientId": "client-42",
                "appointmentId": "future-77",
                "appointmentAt": "2099-10-04T14:30:00+02:00",
            },
        ]
        result = sync.sync_installation(self.installation, upcoming)
        self.assertEqual(result["authoritativeAppointments"], 1)
        inventory = devices.bound_inventory({
            "installationId": self.installation,
            "registrationSecret": self.secret,
        })
        self.assertEqual(inventory["vehicles"], [{
            "bindingId": binding["bindingId"],
            "dueDate": "2027-02-15",
            "appointmentAt": "2099-10-04T14:30:00+02:00",
        }])
        self.assertNotIn("future-77", repr(inventory))
        self.assertNotIn("other-client", repr(inventory))

    def test_elapsed_appointment_does_not_hide_later_match(self):
        binding = self.bind()
        reminders._upsert([{
            "vehicleId": "vehicle-77",
            "clientKind": "account",
            "clientId": "client-42",
            "dueDate": "2099-02-15",
            "appointmentId": "historic-77",
        }])
        result = sync.sync_installation(self.installation, [
            {
                "vehicleId": "vehicle-77",
                "clientKind": "account",
                "clientId": "client-42",
                "appointmentAt": "2020-01-01T09:00:00+00:00",
            },
            {
                "vehicleId": "vehicle-77",
                "clientKind": "account",
                "clientId": "client-42",
                "appointmentAt": "2099-01-01T09:00:00+00:00",
            },
        ])
        self.assertEqual(result["authoritativeAppointments"], 1)
        inventory = devices.bound_inventory({
            "installationId": self.installation,
            "registrationSecret": self.secret,
        })
        self.assertEqual(inventory["vehicles"], [{
            "bindingId": binding["bindingId"],
            "dueDate": "2099-02-15",
            "appointmentAt": "2099-01-01T09:00:00+00:00",
        }])

    def test_refresh_failure_preserves_cached_appointment(self):
        binding = self.bind()
        reminders._upsert([{
            "vehicleId": "vehicle-77",
            "clientKind": "account",
            "clientId": "client-42",
            "dueDate": "2027-02-15",
            "appointmentId": "historic-77",
        }])
        devices.sync_authoritative_deadlines(self.installation, [{
            "deadlineId": binding["bindingId"],
            "dueDate": "2027-02-15",
            "appointmentAt": "2099-10-04T14:30:00+02:00",
        }])
        with mock.patch.object(
            sync,
            "upcoming_appointments_snapshot",
            side_effect=TimeoutError("provider unavailable"),
        ):
            result = sync.sync_installation(
                self.installation,
                refresh_appointments=True,
            )
        self.assertEqual(result["authoritativeDeadlines"], 1)
        inventory = devices.bound_inventory({
            "installationId": self.installation,
            "registrationSecret": self.secret,
        })
        self.assertEqual(
            inventory["vehicles"][0]["appointmentAt"],
            "2099-10-04T14:30:00+02:00",
        )

    def test_strict_refresh_failure_raises_without_mutating_cached_appointment(self):
        binding = self.bind()
        reminders._upsert([{
            "vehicleId": "vehicle-77",
            "clientKind": "account",
            "clientId": "client-42",
            "dueDate": "2027-02-15",
            "appointmentId": "historic-77",
        }])
        devices.sync_authoritative_deadlines(self.installation, [{
            "deadlineId": binding["bindingId"],
            "dueDate": "2027-02-15",
            "appointmentAt": "2099-10-04T14:30:00+02:00",
        }])
        with mock.patch.object(
            sync,
            "upcoming_appointments_snapshot",
            side_effect=TimeoutError("provider unavailable"),
        ):
            with self.assertRaises(TimeoutError):
                sync.sync_installation_fresh(self.installation)

        inventory = devices.bound_inventory({
            "installationId": self.installation,
            "registrationSecret": self.secret,
        })
        self.assertEqual(
            inventory["vehicles"][0]["appointmentAt"],
            "2099-10-04T14:30:00+02:00",
        )

    def test_strict_refresh_removes_stale_appointment_from_fresh_empty_snapshot(self):
        binding = self.bind()
        reminders._upsert([{
            "vehicleId": "vehicle-77",
            "clientKind": "account",
            "clientId": "client-42",
            "dueDate": "2027-02-15",
            "appointmentId": "historic-77",
        }])
        devices.sync_authoritative_deadlines(self.installation, [{
            "deadlineId": binding["bindingId"],
            "dueDate": "2027-02-15",
            "appointmentAt": "2099-10-04T14:30:00+02:00",
        }])
        with mock.patch.object(sync, "upcoming_appointments_snapshot", return_value=[]):
            result = sync.sync_installation_fresh(self.installation)

        self.assertEqual(result.get("authoritativeAppointments", 0), 0)
        inventory = devices.bound_inventory({
            "installationId": self.installation,
            "registrationSecret": self.secret,
        })
        self.assertIsNone(inventory["vehicles"][0]["appointmentAt"])

    def test_strict_refresh_skips_provider_without_eligible_binding(self):
        with mock.patch.object(sync, "upcoming_appointments_snapshot") as snapshot:
            result = sync.sync_installation_fresh(self.installation)

        snapshot.assert_not_called()
        self.assertEqual(result["bindings"], 0)
        self.assertEqual(result["authoritativeAppointments"], 0)

    def test_sync_once_is_noop_without_bindings(self):
        result = sync.sync_once()
        self.assertTrue(result["ok"])
        self.assertEqual(result["installations"], 0)


if __name__ == "__main__":
    unittest.main()
