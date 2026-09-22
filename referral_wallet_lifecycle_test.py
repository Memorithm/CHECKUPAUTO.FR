import tempfile
import unittest
from pathlib import Path

import analytics_store as analytics
import mobile_devices as devices
import referral_engine as referrals
import referral_wallet_claims as claims
import referral_wallet_lifecycle as lifecycle


class ReferralWalletLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_analytics_db = analytics.DB
        self.old_mobile_dir, self.old_mobile_db = devices.DATA_DIR, devices.DB
        analytics.DB = Path(self.tmp.name) / "analytics.sqlite3"
        devices.DATA_DIR = Path(self.tmp.name) / "mobile"
        devices.DB = devices.DATA_DIR / "devices.sqlite3"
        analytics.init_db()
        referrals.init_db()
        devices.init_db()
        claims.init_db()
        self.installation = "60cf7ccf-4297-41f4-b76b-c0bd44dbe3d1"
        self.secret = "A" * 43
        self.payload = {
            "installationId": self.installation,
            "registrationSecret": self.secret,
        }
        devices.register_installation(self.payload)
        self.account = referrals.create_account("OWNER-7K4P")
        token = claims.issue(self.account["code"])["claimToken"]
        claims.consume({**self.payload, "claimToken": token})

    def tearDown(self):
        analytics.DB = self.old_analytics_db
        devices.DATA_DIR, devices.DB = self.old_mobile_dir, self.old_mobile_db
        self.tmp.cleanup()

    def _owner_count(self):
        with analytics.connect() as db:
            return int(db.execute("SELECT COUNT(*) n FROM referral_wallet_owner").fetchone()["n"])

    def _mobile_count(self):
        with devices.connect() as db:
            return int(db.execute("SELECT COUNT(*) n FROM mobile_device").fetchone()["n"])

    def test_delete_releases_wallet_ownership_before_removing_installation(self):
        self.assertEqual(self._owner_count(), 1)
        result = lifecycle.delete_installation(self.payload)
        self.assertTrue(result["ok"])
        self.assertTrue(result["removed"])
        self.assertEqual(result["referralWalletOwnershipReleased"], 1)
        self.assertEqual(self._owner_count(), 0)
        self.assertEqual(self._mobile_count(), 0)
        self.assertNotIn(self.installation, str(result))
        self.assertNotIn(self.secret, str(result))

    def test_wrong_secret_cannot_release_or_delete(self):
        with self.assertRaises(PermissionError):
            lifecycle.delete_installation({
                "installationId": self.installation,
                "registrationSecret": "B" * 43,
            })
        self.assertEqual(self._owner_count(), 1)
        self.assertEqual(self._mobile_count(), 1)
        self.assertTrue(claims.ownership_matches(self.account["id"], self.installation))

    def test_release_is_idempotent_for_authenticated_installation(self):
        first = lifecycle.release_for_authenticated_installation(self.payload)
        second = lifecycle.release_for_authenticated_installation(self.payload)
        self.assertEqual(first["released"], 1)
        self.assertEqual(second["released"], 0)
        self.assertFalse(first["rawInstallationPersisted"])
        self.assertEqual(self._owner_count(), 0)

    def test_release_rejects_ambiguous_payload(self):
        with self.assertRaises(ValueError):
            lifecycle.release_for_authenticated_installation({**self.payload, "extra": True})
        self.assertEqual(self._owner_count(), 1)

    def test_released_wallet_can_be_claimed_by_a_new_authenticated_installation(self):
        lifecycle.delete_installation(self.payload)
        other_installation = "4fb1e2f8-fd94-49af-8642-b6aad6f6c721"
        other_secret = "C" * 43
        devices.register_installation({
            "installationId": other_installation,
            "registrationSecret": other_secret,
        })
        token = claims.issue(self.account["code"])["claimToken"]
        result = claims.consume({
            "installationId": other_installation,
            "registrationSecret": other_secret,
            "claimToken": token,
        })
        self.assertTrue(result["ok"])
        self.assertTrue(claims.ownership_matches(self.account["id"], other_installation))


if __name__ == "__main__":
    unittest.main()
