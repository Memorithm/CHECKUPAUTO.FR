import tempfile
import unittest
from pathlib import Path

import mobile_devices as devices


class MobileDevicesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_dir, self.old_db = devices.DATA_DIR, devices.DB
        devices.DATA_DIR = Path(self.tmp.name); devices.DB = devices.DATA_DIR / "devices.sqlite3"
        devices.init_db()
        self.install_id = "60cf7ccf-4297-41f4-b76b-c0bd44dbe3d1"
        self.secret = "A" * 43
        self.token = "ab" * 32

    def tearDown(self):
        devices.DATA_DIR, devices.DB = self.old_dir, self.old_db
        self.tmp.cleanup()

    def payload(self, **changes):
        data = {"installationId": self.install_id, "registrationSecret": self.secret,
                "deviceToken": self.token, "environment": "sandbox"}
        data.update(changes); return data

    def test_init_db_migrates_existing_registry_without_disabled_reason(self):
        devices.DB.unlink(missing_ok=True)
        with devices.connect() as db:
            db.execute("""CREATE TABLE mobile_device(
              installation_id TEXT PRIMARY KEY, secret_hash TEXT NOT NULL, device_token TEXT NOT NULL,
              token_hash TEXT NOT NULL, environment TEXT NOT NULL, created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, disabled_at TEXT NOT NULL DEFAULT ''
            )""")
        devices.init_db()
        with devices.connect() as db:
            columns = {row["name"] for row in db.execute("PRAGMA table_info(mobile_device)")}
        self.assertIn("disabled_reason", columns)

    def test_init_db_migrates_existing_deadlines_to_device_source(self):
        devices.DB.unlink(missing_ok=True)
        with devices.connect() as db:
            db.execute("""CREATE TABLE mobile_deadline(
              installation_id TEXT NOT NULL,
              deadline_id TEXT NOT NULL,
              due_date TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              PRIMARY KEY(installation_id,deadline_id)
            )""")
            db.execute(
                """INSERT INTO mobile_deadline(
                   installation_id,deadline_id,due_date,created_at,updated_at
                   ) VALUES(?,?,?,?,?)""",
                (
                    self.install_id,
                    "e62c0b27-2141-4f5c-b2f4-1e458aa6a6ca",
                    "2027-01-15",
                    "2026-09-19T00:00:00+00:00",
                    "2026-09-19T00:00:00+00:00",
                ),
            )
        devices.init_db()
        with devices.connect() as db:
            columns = {row["name"] for row in db.execute("PRAGMA table_info(mobile_deadline)")}
            row = db.execute("SELECT source FROM mobile_deadline").fetchone()
        self.assertIn("source", columns)
        self.assertEqual(row["source"], devices.DEVICE_DEADLINE_SOURCE)

    def test_register_keeps_token_private_from_status(self):
        result = devices.register(self.payload())
        self.assertTrue(result["ok"]); self.assertEqual(devices.status()["active"], 1)
        self.assertNotIn(self.token, str(devices.status()))
        self.assertEqual(devices.active_targets()[0]["device_token"], self.token)

    def test_registration_secret_prevents_takeover(self):
        devices.register(self.payload())
        with self.assertRaises(PermissionError):
            devices.register(self.payload(registrationSecret="B" * 43, deviceToken="cd" * 32))
        self.assertEqual(devices.active_targets()[0]["device_token"], self.token)

    def test_unregister_requires_secret_and_clears_raw_token(self):
        devices.register(self.payload())
        with self.assertRaises(PermissionError):
            devices.unregister({"installationId": self.install_id, "registrationSecret": "B" * 43})
        result = devices.unregister({"installationId": self.install_id, "registrationSecret": self.secret})
        self.assertTrue(result["removed"]); self.assertEqual(devices.status()["active"], 0)
        self.assertNotIn(self.token.encode(), devices.DB.read_bytes())

    def test_deadline_snapshot_is_authenticated_and_contains_only_opaque_dates(self):
        devices.register(self.payload())
        deadline_id = "e62c0b27-2141-4f5c-b2f4-1e458aa6a6ca"
        result = devices.sync_deadlines({
            "installationId": self.install_id, "registrationSecret": self.secret,
            "deadlines": [{"deadlineId": deadline_id, "dueDate": "2027-01-15"}],
        })
        self.assertEqual(result["deadlineCount"], 1)
        targets = devices.due_targets("2027-01-01", "2027-02-01")
        self.assertEqual(targets[0]["deadline_id"], deadline_id)
        self.assertEqual(targets[0]["due_date"], "2027-01-15")
        raw = devices.DB.read_bytes()
        self.assertNotIn(b"AA-123-AA", raw)

    def test_deadline_snapshot_replaces_removed_items(self):
        devices.register(self.payload())
        first = "e62c0b27-2141-4f5c-b2f4-1e458aa6a6ca"
        second = "936246c1-8932-4b6f-92b6-1ea591c09f96"
        base = {"installationId": self.install_id, "registrationSecret": self.secret}
        devices.sync_deadlines(base | {"deadlines": [
            {"deadlineId": first, "dueDate": "2027-01-15"},
            {"deadlineId": second, "dueDate": "2027-02-15"},
        ]})
        devices.sync_deadlines(base | {"deadlines": [{"deadlineId": second, "dueDate": "2027-03-15"}]})
        targets = devices.due_targets("2027-01-01", "2027-04-01")
        self.assertEqual([(r["deadline_id"], r["due_date"]) for r in targets], [(second, "2027-03-15")])

    def test_authoritative_deadlines_suppress_device_fallback_without_deleting_it(self):
        devices.register(self.payload())
        device_id = "e62c0b27-2141-4f5c-b2f4-1e458aa6a6ca"
        mercure_id = "936246c1-8932-4b6f-92b6-1ea591c09f96"
        base = {"installationId": self.install_id, "registrationSecret": self.secret}
        devices.sync_deadlines(base | {"deadlines": [
            {"deadlineId": device_id, "dueDate": "2027-01-15"},
        ]})
        devices.sync_authoritative_deadlines(self.install_id, [
            {"deadlineId": mercure_id, "dueDate": "2027-02-15"},
        ])

        targets = devices.due_targets("2027-01-01", "2027-03-01")
        self.assertEqual(
            [(row["deadline_id"], row["source"]) for row in targets],
            [(mercure_id, devices.AUTHORITATIVE_DEADLINE_SOURCE)],
        )
        state = devices.status()
        self.assertEqual(state["deadlinesBySource"][devices.DEVICE_DEADLINE_SOURCE], 1)
        self.assertEqual(state["deadlinesBySource"][devices.AUTHORITATIVE_DEADLINE_SOURCE], 1)

        devices.sync_authoritative_deadlines(self.install_id, [])
        fallback = devices.due_targets("2027-01-01", "2027-03-01")
        self.assertEqual(
            [(row["deadline_id"], row["source"]) for row in fallback],
            [(device_id, devices.DEVICE_DEADLINE_SOURCE)],
        )

    def test_device_snapshot_cannot_overwrite_authoritative_deadline(self):
        devices.register(self.payload())
        deadline_id = "e62c0b27-2141-4f5c-b2f4-1e458aa6a6ca"
        devices.sync_authoritative_deadlines(self.install_id, [
            {"deadlineId": deadline_id, "dueDate": "2027-02-15"},
        ])
        with self.assertRaisesRegex(ValueError, "source autoritaire"):
            devices.sync_deadlines({
                "installationId": self.install_id,
                "registrationSecret": self.secret,
                "deadlines": [{"deadlineId": deadline_id, "dueDate": "2027-03-15"}],
            })
        target = devices.due_targets("2027-02-01", "2027-04-01")[0]
        self.assertEqual(target["due_date"], "2027-02-15")
        self.assertEqual(target["source"], devices.AUTHORITATIVE_DEADLINE_SOURCE)

    def test_authoritative_sync_requires_active_registered_installation(self):
        with self.assertRaises(LookupError):
            devices.sync_authoritative_deadlines(self.install_id, [])

    def test_deadline_sync_requires_registered_secret_and_unregister_purges(self):
        devices.register(self.payload())
        payload = {"installationId": self.install_id, "registrationSecret": "B" * 43, "deadlines": []}
        with self.assertRaises(PermissionError):
            devices.sync_deadlines(payload)
        good = payload | {"registrationSecret": self.secret, "deadlines": [
            {"deadlineId": "e62c0b27-2141-4f5c-b2f4-1e458aa6a6ca", "dueDate": "2027-01-15"}
        ]}
        devices.sync_deadlines(good)
        devices.unregister({"installationId": self.install_id, "registrationSecret": self.secret})
        self.assertEqual(devices.status()["deadlines"], 0)

    def test_token_reassignment_purges_deadlines_from_disabled_installation(self):
        devices.register(self.payload())
        devices.sync_deadlines({
            "installationId": self.install_id, "registrationSecret": self.secret,
            "deadlines": [{"deadlineId": "e62c0b27-2141-4f5c-b2f4-1e458aa6a6ca", "dueDate": "2027-01-15"}],
        })
        replacement_id = "936246c1-8932-4b6f-92b6-1ea591c09f96"
        devices.register({
            "installationId": replacement_id, "registrationSecret": "C" * 43,
            "deviceToken": self.token, "environment": "sandbox",
        })
        self.assertEqual(devices.status()["deadlines"], 0)
        self.assertEqual(devices.active_targets()[0]["installation_id"], replacement_id)

    def test_apns_invalid_token_disable_is_compare_and_clear_and_purges_deadlines(self):
        devices.register(self.payload())
        devices.sync_deadlines({
            "installationId": self.install_id, "registrationSecret": self.secret,
            "deadlines": [{"deadlineId": "e62c0b27-2141-4f5c-b2f4-1e458aa6a6ca", "dueDate": "2027-01-15"}],
        })
        stale = devices.disable_invalid_token(self.install_id, "cd" * 32, "apns:Unregistered")
        self.assertFalse(stale["disabled"])
        self.assertEqual(devices.status()["active"], 1)
        result = devices.disable_invalid_token(self.install_id, self.token, "apns:Unregistered")
        self.assertTrue(result["disabled"])
        state = devices.status()
        self.assertEqual(state["active"], 0)
        self.assertEqual(state["deadlines"], 0)
        self.assertEqual(state["disabledByReason"]["apns:Unregistered"], 1)
        self.assertNotIn(self.token.encode(), devices.DB.read_bytes())

    def test_rejects_malformed_inputs(self):
        with self.assertRaises(ValueError): devices.register(self.payload(installationId="bad"))
        with self.assertRaises(ValueError): devices.register(self.payload(deviceToken="xyz"))
        with self.assertRaises(ValueError): devices.register(self.payload(environment="other"))


if __name__ == "__main__": unittest.main()
