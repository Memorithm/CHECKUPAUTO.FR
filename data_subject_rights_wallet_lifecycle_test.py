import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import analytics_store as analytics
import compliance_store
import data_subject_rights as rights
import mobile_devices as devices
import referral_engine as referrals
import referral_wallet_claims as claims


class DataSubjectRightsWalletLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        for target, name, value in (
            (analytics, "DB", root / "analytics.sqlite3"),
            (devices, "DATA_DIR", root / "mobile"),
            (devices, "DB", root / "mobile" / "devices.sqlite3"),
        ):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.compliance_db = root / "compliance.sqlite3"
        analytics.init_db()
        claims.init_db()
        self.installations = (
            "60cf7ccf-4297-41f4-b76b-c0bd44dbe3d1",
            "4fb1e2f8-fd94-49af-8642-b6aad6f6c721",
        )
        self.accounts = []
        for index, installation in enumerate(self.installations):
            payload = {
                "installationId": installation,
                "registrationSecret": chr(65 + index) * 43,
            }
            devices.register_installation(payload)
            account = referrals.create_account("OWNER-TEST-" + str(index))
            self.accounts.append(account)
            token = claims.issue(account["code"])["claimToken"]
            claims.consume({**payload, "claimToken": token})
            with analytics.connect() as db:
                db.execute(
                    """INSERT INTO referral_ledger(
                         account_id,kind,amount_cents,reference,created_at
                       ) VALUES(?,?,?,?,?)""",
                    (account["id"], "earn", 500, "test-earned-" + str(index),
                     "2026-09-22T00:00:00+00:00"),
                )

    def request(self, request_type="erasure"):
        return compliance_store.create_rights_request(
            {"type": request_type, "subjectRef": self.installations[0]},
            self.compliance_db,
        )

    def execute(self, request, installation=None):
        return rights.execute(
            request["id"], installation or self.installations[0],
            adapter="mobile_installation", db_path=self.compliance_db,
        )

    def owner_hashes(self):
        with analytics.connect() as db:
            return sorted(row[0] for row in db.execute(
                "SELECT installation_hash FROM referral_wallet_owner"
            ))

    def mobile_ids(self):
        with devices.connect() as db:
            return sorted(row[0] for row in db.execute(
                "SELECT installation_id FROM mobile_device"
            ))

    def ledger(self):
        with analytics.connect() as db:
            return {
                "accounts": [tuple(row) for row in db.execute(
                    "SELECT * FROM referral_accounts ORDER BY id"
                )],
                "entries": [tuple(row) for row in db.execute(
                    "SELECT * FROM referral_ledger ORDER BY id"
                )],
            }

    def block_release(self):
        with analytics.connect() as db:
            db.executescript("""
                CREATE TRIGGER test_refuse_owner_release
                BEFORE DELETE ON referral_wallet_owner
                BEGIN SELECT RAISE(ABORT, 'test release failure'); END;
            """)

    def test_erasure_releases_only_verified_ownership_and_preserves_balances(self):
        before = self.ledger()
        request = self.request()
        result = self.execute(request)
        self.assertEqual(self.owner_hashes(), [
            hashlib.sha256(self.installations[1].encode()).hexdigest()
        ])
        self.assertEqual(self.mobile_ids(), [self.installations[1]])
        self.assertEqual(self.ledger(), before)
        self.assertEqual(result["referralWalletOwnershipReleased"], 1)
        self.assertFalse(result["requestComplete"])
        self.assertEqual(result["requestStatus"], "in_progress")
        audit = rights.audit_rows(self.compliance_db)
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["action"], "erase")
        for private in (*self.installations, *(a["id"] for a in self.accounts), "A" * 43):
            self.assertNotIn(private, repr(result))
            self.assertNotIn(private, repr(audit))

    def test_wrong_subject_cannot_release_another_installations_wallet(self):
        owners, mobiles = self.owner_hashes(), self.mobile_ids()
        with self.assertRaises(PermissionError):
            self.execute(self.request(), self.installations[1])
        self.assertEqual(self.owner_hashes(), owners)
        self.assertEqual(self.mobile_ids(), mobiles)
        self.assertEqual(rights.audit_rows(self.compliance_db), [])

    def test_release_failure_aborts_mobile_erasure_and_audit(self):
        self.block_release()
        owners, mobiles, ledger = self.owner_hashes(), self.mobile_ids(), self.ledger()
        with self.assertRaises(sqlite3.IntegrityError):
            self.execute(self.request())
        self.assertEqual(self.owner_hashes(), owners)
        self.assertEqual(self.mobile_ids(), mobiles)
        self.assertEqual(self.ledger(), ledger)
        self.assertEqual(rights.audit_rows(self.compliance_db), [])
        self.assertEqual(compliance_store.rights_requests(self.compliance_db)[0]["status"], "open")

    def test_same_request_can_retry_after_release_failure(self):
        request = self.request()
        self.block_release()
        with self.assertRaises(sqlite3.IntegrityError):
            self.execute(request)
        with analytics.connect() as db:
            db.execute("DROP TRIGGER test_refuse_owner_release")
        result = self.execute(request)
        self.assertEqual(result["referralWalletOwnershipReleased"], 1)
        self.assertEqual(len(rights.audit_rows(self.compliance_db)), 1)

    def test_verified_erasure_does_not_require_an_active_device_or_its_secret(self):
        with devices.connect() as db:
            db.execute("UPDATE mobile_device SET disabled_at=? WHERE installation_id=?",
                       ("2026-09-22T00:00:00+00:00", self.installations[0]))
        result = self.execute(self.request())
        self.assertEqual(result["referralWalletOwnershipReleased"], 1)
        self.assertEqual(self.mobile_ids(), [self.installations[1]])

    def test_existing_orphaned_ownership_can_be_removed_by_verified_erasure(self):
        with devices.connect() as db:
            db.execute("DELETE FROM mobile_device WHERE installation_id=?", (self.installations[0],))
        result = self.execute(self.request())
        self.assertEqual(result["removed"]["deviceRecords"], 0)
        self.assertEqual(result["referralWalletOwnershipReleased"], 1)
        self.assertEqual(len(self.owner_hashes()), 1)

    def test_access_and_portability_do_not_release_ownership(self):
        before = self.owner_hashes()
        for request_type in ("access", "portability"):
            with self.subTest(request_type=request_type):
                self.execute(self.request(request_type))
                self.assertEqual(self.owner_hashes(), before)


if __name__ == "__main__":
    unittest.main()
