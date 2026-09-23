import datetime
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

import analytics_store
import compliance_store
import mobile_devices
import referral_wallet_claims
import referral_wallet_lifecycle
import retention_enforcement as retention


class RetentionMobileLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.old_env = {
            key: os.environ.get(key)
            for key in ("CYBERCHECK_DATA_DIR", "CYBERCHECK_PRIVATE_DIR")
        }
        os.environ["CYBERCHECK_DATA_DIR"] = str(self.root / "mobile")
        os.environ["CYBERCHECK_PRIVATE_DIR"] = str(self.root / "private")
        self.addCleanup(self._restore_env)

        self.old_analytics_db = analytics_store.DB
        self.old_mobile_dir = mobile_devices.DATA_DIR
        self.old_mobile_db = mobile_devices.DB
        analytics_store.DB = self.root / "analytics.sqlite3"
        mobile_devices.DATA_DIR = self.root / "mobile"
        mobile_devices.DB = mobile_devices.DATA_DIR / "mobile.sqlite3"
        self.addCleanup(self._restore_globals)

        self.compliance_db = self.root / "compliance.sqlite3"
        compliance_store.init_db(self.compliance_db)
        retention.init_db(self.compliance_db)

    def _restore_env(self):
        for key, value in self.old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _restore_globals(self):
        analytics_store.DB = self.old_analytics_db
        mobile_devices.DATA_DIR = self.old_mobile_dir
        mobile_devices.DB = self.old_mobile_db

    @staticmethod
    def _iso(days_ago: int) -> str:
        return (
            datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(days=days_ago)
        ).isoformat(timespec="seconds")

    def _inactive_installation(self, *, disabled_days_ago: int = 45) -> tuple[str, str, str]:
        installation_id = str(uuid.uuid4())
        registration_secret = "test_registration_secret_0123456789"
        mobile_devices.register_installation({
            "installationId": installation_id,
            "registrationSecret": registration_secret,
        })
        deadline_id = str(uuid.uuid4())
        binding_id = str(uuid.uuid4())
        with mobile_devices.connect() as db:
            db.execute(
                """UPDATE mobile_device
                   SET disabled_at=?,disabled_reason='retention-test',updated_at=?
                   WHERE installation_id=?""",
                (self._iso(disabled_days_ago), self._iso(disabled_days_ago), installation_id),
            )
            db.execute(
                """INSERT INTO mobile_deadline(
                     installation_id,deadline_id,due_date,source,created_at,updated_at
                   ) VALUES(?,?,?,?,?,?)""",
                (
                    installation_id,
                    deadline_id,
                    "2030-01-01",
                    mobile_devices.DEVICE_DEADLINE_SOURCE,
                    self._iso(disabled_days_ago),
                    self._iso(disabled_days_ago),
                ),
            )
            db.execute(
                """INSERT INTO mobile_vehicle_binding(
                     binding_id,installation_id,vehicle_id,client_kind,client_id,created_at,updated_at
                   ) VALUES(?,?,?,?,?,?,?)""",
                (
                    binding_id,
                    installation_id,
                    "vehicle-retention-test",
                    "account",
                    "client-retention-test",
                    self._iso(disabled_days_ago),
                    self._iso(disabled_days_ago),
                ),
            )

        referral_wallet_claims.init_db()
        account_id = str(uuid.uuid4())
        installation_hash = referral_wallet_lifecycle._installation_hash(installation_id)
        with analytics_store.connect() as db:
            db.execute(
                """INSERT INTO referral_accounts(
                     id,code,created_at,active,reward_cents,currency
                   ) VALUES(?,?,?,?,?,?)""",
                (account_id, "CA-RETTEST1", self._iso(60), 1, 500, "EUR"),
            )
            db.execute(
                """INSERT INTO referral_wallet_owner(
                     account_id,installation_hash,claimed_at,evidence_hash
                   ) VALUES(?,?,?,?)""",
                (account_id, installation_hash, self._iso(50), "a" * 64),
            )
        return installation_id, registration_secret, account_id

    def _owner_count(self, account_id: str) -> int:
        with analytics_store.connect() as db:
            return int(db.execute(
                "SELECT COUNT(*) n FROM referral_wallet_owner WHERE account_id=?",
                (account_id,),
            ).fetchone()["n"])

    def test_purge_releases_wallet_and_persists_minimised_erasure_receipt(self):
        installation_id, registration_secret, account_id = self._inactive_installation()

        removed = retention._purge_inactive_mobile(30, dry_run=False)

        self.assertEqual(removed, 1)
        self.assertEqual(self._owner_count(account_id), 0)
        with mobile_devices.connect() as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) n FROM mobile_device WHERE installation_id=?",
                (installation_id,),
            ).fetchone()["n"], 0)
            self.assertEqual(db.execute(
                "SELECT COUNT(*) n FROM mobile_deadline WHERE installation_id=?",
                (installation_id,),
            ).fetchone()["n"], 0)
            self.assertEqual(db.execute(
                "SELECT COUNT(*) n FROM mobile_vehicle_binding WHERE installation_id=?",
                (installation_id,),
            ).fetchone()["n"], 0)

        receipt = referral_wallet_lifecycle.mobile_erasure_receipt_by_subject_hash(
            referral_wallet_lifecycle._installation_hash(installation_id)
        )
        self.assertIsNotNone(receipt)
        self.assertEqual(receipt["removed"], {
            "deviceRecords": 1,
            "deadlineRecords": 1,
            "vehicleBindingRecords": 1,
        })
        self.assertEqual(len(receipt["evidenceHash"]), 64)
        self.assertNotIn(installation_id, repr(receipt))
        self.assertNotIn(registration_secret, repr(receipt))

    def test_dry_run_counts_without_releasing_wallet_or_erasing_mobile_state(self):
        installation_id, _, account_id = self._inactive_installation()

        removed = retention._purge_inactive_mobile(30, dry_run=True)

        self.assertEqual(removed, 1)
        self.assertEqual(self._owner_count(account_id), 1)
        with mobile_devices.connect() as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) n FROM mobile_device WHERE installation_id=?",
                (installation_id,),
            ).fetchone()["n"], 1)
            self.assertEqual(db.execute(
                "SELECT COUNT(*) n FROM mobile_deadline WHERE installation_id=?",
                (installation_id,),
            ).fetchone()["n"], 1)
            self.assertEqual(db.execute(
                "SELECT COUNT(*) n FROM mobile_vehicle_binding WHERE installation_id=?",
                (installation_id,),
            ).fetchone()["n"], 1)

    def test_revalidation_refuses_installation_that_is_no_longer_retention_eligible(self):
        installation_id, _, account_id = self._inactive_installation()
        cutoff = retention._cutoff(30)
        with mobile_devices.connect() as db:
            db.execute(
                "UPDATE mobile_device SET disabled_at=?,updated_at=? WHERE installation_id=?",
                (self._iso(2), self._iso(2), installation_id),
            )

        result = referral_wallet_lifecycle.purge_inactive_installation(
            installation_id,
            cutoff,
        )

        self.assertTrue(result["ok"])
        self.assertFalse(result["eligible"])
        self.assertFalse(result["removed"])
        self.assertEqual(self._owner_count(account_id), 1)
        with mobile_devices.connect() as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) n FROM mobile_device WHERE installation_id=?",
                (installation_id,),
            ).fetchone()["n"], 1)

    def test_lifecycle_failure_propagates_without_reporting_a_successful_purge(self):
        installation_id, _, account_id = self._inactive_installation()
        with mock.patch.object(
            retention.referral_wallet_lifecycle,
            "purge_inactive_installation",
            side_effect=RuntimeError("simulated retention lifecycle failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "simulated retention lifecycle failure"):
                retention._purge_inactive_mobile(30, dry_run=False)

        self.assertEqual(self._owner_count(account_id), 1)
        with mobile_devices.connect() as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) n FROM mobile_device WHERE installation_id=?",
                (installation_id,),
            ).fetchone()["n"], 1)


if __name__ == "__main__":
    unittest.main()
