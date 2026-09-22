import tempfile
import unittest
from pathlib import Path

import analytics_store as analytics
import mobile_devices as devices
import referral_engine as referrals
import referral_wallet_claims as wallet_claims


class MobileInventoryWalletTest(unittest.TestCase):
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
        wallet_claims.init_db()
        self.installation = "60cf7ccf-4297-41f4-b76b-c0bd44dbe3d1"
        self.secret = "A" * 43
        self.payload = {
            "installationId": self.installation,
            "registrationSecret": self.secret,
        }
        devices.register_installation(self.payload)

    def tearDown(self):
        analytics.DB = self.old_analytics_db
        devices.DATA_DIR, devices.DB = self.old_mobile_dir, self.old_mobile_db
        self.tmp.cleanup()

    def test_unbound_installation_receives_empty_verified_wallet_status(self):
        result = devices.bound_inventory(self.payload)
        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "mercure")
        self.assertEqual(result["vehicles"], [])
        wallet = result["referralWalletStatus"]
        self.assertTrue(wallet["ok"])
        self.assertEqual(wallet["walletCount"], 0)
        self.assertEqual(wallet["wallets"], [])
        self.assertFalse(wallet["shareCodeIsOwnershipProof"])
        self.assertFalse(wallet["accountIdentifiersExposed"])
        self.assertFalse(wallet["thirdPartyAppointmentIdentifiersExposed"])
        self.assertFalse(wallet["ledgerReferencesExposed"])

    def test_owned_wallet_is_projected_without_internal_or_third_party_identifiers(self):
        account = referrals.create_account("MOBILE-WALLET-7K4P")
        token = wallet_claims.issue(account["code"])["claimToken"]
        wallet_claims.consume({**self.payload, "claimToken": token})
        with analytics.connect() as db:
            db.execute(
                """INSERT INTO referral_rewards(
                   provider,external_id,account_id,referral_code,status,reward_cents,
                   attribution_token,created_at,updated_at
                   ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    "mercure-rdv",
                    "appointment-sensitive-987",
                    account["id"],
                    account["code"],
                    "earned",
                    500,
                    "attribution-sensitive-987",
                    "2026-09-22T00:00:00+00:00",
                    "2026-09-22T00:00:00+00:00",
                ),
            )
            db.execute(
                """INSERT INTO referral_ledger(
                   account_id,kind,amount_cents,reference,created_at,note
                   ) VALUES(?,?,?,?,?,?)""",
                (
                    account["id"],
                    "earn",
                    500,
                    "ledger-sensitive-987",
                    "2026-09-22T00:00:00+00:00",
                    "Crédit de test",
                ),
            )

        result = devices.bound_inventory(self.payload)
        wallet = result["referralWalletStatus"]
        self.assertEqual(wallet["walletCount"], 1)
        self.assertEqual(wallet["wallets"][0]["referralCode"], account["code"])
        self.assertEqual(wallet["wallets"][0]["balanceCents"], 500)
        serialized = repr(result)
        self.assertNotIn(account["id"], serialized)
        self.assertNotIn(self.installation, serialized)
        self.assertNotIn(self.secret, serialized)
        self.assertNotIn("appointment-sensitive-987", serialized)
        self.assertNotIn("attribution-sensitive-987", serialized)
        self.assertNotIn("ledger-sensitive-987", serialized)

    def test_wrong_mobile_secret_cannot_read_vehicle_or_wallet_state(self):
        account = referrals.create_account("MOBILE-WALLET-9Q2M")
        token = wallet_claims.issue(account["code"])["claimToken"]
        wallet_claims.consume({**self.payload, "claimToken": token})
        with self.assertRaises(PermissionError):
            devices.bound_inventory(
                {
                    "installationId": self.installation,
                    "registrationSecret": "B" * 43,
                }
            )


if __name__ == "__main__":
    unittest.main()
