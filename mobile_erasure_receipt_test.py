import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import mobile_devices
import referral_wallet_lifecycle as lifecycle

INSTALLATION_ID = "11111111-1111-1111-1111-111111111111"
TEST_SECRET = "unit-test-secret-value-000000000001"


class MobileErasureReceiptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.data_patch = mock.patch.object(mobile_devices, "DATA_DIR", root)
        self.db_patch = mock.patch.object(mobile_devices, "DB", root / "mobile.sqlite3")
        self.data_patch.start(); self.db_patch.start()
        mobile_devices.init_db()

    def tearDown(self):
        self.db_patch.stop(); self.data_patch.stop(); self.tmp.cleanup()

    def seed(self):
        now = mobile_devices._now_iso()
        with mobile_devices.connect() as db:
            db.execute(
                """INSERT INTO mobile_device(
                installation_id,secret_hash,device_token,token_hash,environment,
                created_at,updated_at,last_seen_at,disabled_at,disabled_reason)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (INSTALLATION_ID, mobile_devices._hash(TEST_SECRET), "", "", "production", now, now, now, "", ""),
            )
            db.execute(
                "INSERT INTO mobile_deadline VALUES(?,?,?,?,?,?)",
                (INSTALLATION_ID, "22222222-2222-2222-2222-222222222222", "2027-01-10", "device", now, now),
            )
            db.execute(
                "INSERT INTO mobile_vehicle_binding VALUES(?,?,?,?,?,?,?)",
                ("33333333-3333-3333-3333-333333333333", INSTALLATION_ID, "vehicle-1", "account", "customer-1", now, now),
            )

    def payload(self):
        return {"installationId": INSTALLATION_ID, "registrationSecret": TEST_SECRET}

    def test_delete_creates_privacy_minimised_receipt_and_retry_is_idempotent(self):
        self.seed()
        release = {"ok": True, "released": 2, "rawInstallationPersisted": False}
        with mock.patch.object(lifecycle, "_release_installation_ownership", return_value=release) as mocked:
            first = lifecycle.delete_installation(self.payload())
            second = lifecycle.delete_installation(self.payload())
        self.assertEqual(first["removed"], True)
        self.assertEqual(second["removed"], False)
        mocked.assert_called_once_with(INSTALLATION_ID)
        digest = hashlib.sha256(INSTALLATION_ID.encode()).hexdigest()
        receipt = lifecycle.mobile_erasure_receipt_by_subject_hash(digest)
        self.assertEqual(receipt["removed"], {"deviceRecords": 1, "deadlineRecords": 1, "vehicleBindingRecords": 1})
        self.assertFalse(receipt["rawInstallationPersisted"])
        with mobile_devices.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) n FROM mobile_device").fetchone()["n"], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) n FROM mobile_erasure_receipt").fetchone()["n"], 1)
            stored = repr(dict(db.execute("SELECT * FROM mobile_erasure_receipt").fetchone()))
        self.assertNotIn(INSTALLATION_ID, stored)
        self.assertNotIn(TEST_SECRET, stored)

    def test_receipt_write_failure_rolls_back_mobile_rows(self):
        self.seed(); lifecycle._init_mobile_erasure_receipts()
        with mobile_devices.connect() as db:
            db.execute("""CREATE TRIGGER fail_receipt BEFORE INSERT ON mobile_erasure_receipt
                       BEGIN SELECT RAISE(ABORT, 'receipt failure'); END""")
        release = {"ok": True, "released": 0, "rawInstallationPersisted": False}
        with mock.patch.object(lifecycle, "_release_installation_ownership", return_value=release):
            with self.assertRaisesRegex(sqlite3.IntegrityError, "receipt failure"):
                lifecycle.delete_installation(self.payload())
        with mobile_devices.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) n FROM mobile_device").fetchone()["n"], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) n FROM mobile_deadline").fetchone()["n"], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) n FROM mobile_vehicle_binding").fetchone()["n"], 1)


if __name__ == "__main__":
    unittest.main()
