import hashlib
import tempfile
import unittest
from pathlib import Path

import analytics_store as analytics
import mobile_devices as devices
import referral_engine as referrals
import referral_wallet_claims as claims
import referral_wallet_mobile as mobile_wallet


class ReferralWalletMobileStatusTest(unittest.TestCase):
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
        devices.register_installation({
            "installationId": self.installation,
            "registrationSecret": self.secret,
        })
        self.account = referrals.create_account("OWNER-7K4P")

    def tearDown(self):
        analytics.DB = self.old_analytics_db
        devices.DATA_DIR, devices.DB = self.old_mobile_dir, self.old_mobile_db
        self.tmp.cleanup()

    def payload(self, **changes):
        value = {
            "installationId": self.installation,
            "registrationSecret": self.secret,
        }
        value.update(changes)
        return value

    def bind(self, account=None):
        account = account or self.account
        token = claims.issue(account["code"])["claimToken"]
        claims.consume({**self.payload(), "claimToken": token})

    def test_authenticated_unbound_installation_gets_empty_status(self):
        result = mobile_wallet.status(self.payload())
        self.assertTrue(result["ok"])
        self.assertEqual(result["walletCount"], 0)
        self.assertEqual(result["wallets"], [])
        self.assertFalse(result["shareCodeIsOwnershipProof"])
        self.assertFalse(result["accountIdentifiersExposed"])
        self.assertFalse(result["thirdPartyAppointmentIdentifiersExposed"])
        self.assertFalse(result["ledgerReferencesExposed"])

    def test_owned_wallet_returns_bounded_product_status(self):
        self.bind()
        with analytics.connect() as db:
            db.execute(
                """INSERT INTO referral_rewards(
                   provider,external_id,account_id,referral_code,status,reward_cents,
                   attribution_token,created_at,updated_at
                   ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    "mercure-rdv",
                    "appointment-sensitive-123",
                    self.account["id"],
                    self.account["code"],
                    "pending",
                    500,
                    "attr-sensitive-123",
                    "2026-09-22T00:00:00+00:00",
                    "2026-09-22T00:00:00+00:00",
                ),
            )
            db.execute(
                """INSERT INTO referral_ledger(
                   account_id,kind,amount_cents,reference,created_at,note
                   ) VALUES(?,?,?,?,?,?)""",
                (
                    self.account["id"],
                    "earn",
                    500,
                    "ledger-sensitive-123",
                    "2026-09-22T00:00:00+00:00",
                    "Crédit de test",
                ),
            )

        result = mobile_wallet.status(self.payload())
        self.assertEqual(result["walletCount"], 1)
        wallet = result["wallets"][0]
        self.assertEqual(wallet["referralCode"], self.account["code"])
        self.assertEqual(wallet["currency"], "EUR")
        self.assertEqual(wallet["balanceCents"], 500)
        self.assertEqual(wallet["pendingCents"], 500)
        self.assertEqual(wallet["pendingReferrals"], 1)
        serialized = repr(result)
        self.assertNotIn(self.account["id"], serialized)
        self.assertNotIn(self.installation, serialized)
        self.assertNotIn(self.secret, serialized)
        self.assertNotIn("appointment-sensitive-123", serialized)
        self.assertNotIn("attr-sensitive-123", serialized)
        self.assertNotIn("ledger-sensitive-123", serialized)

    def test_wrong_secret_is_refused(self):
        self.bind()
        with self.assertRaises(PermissionError):
            mobile_wallet.status(self.payload(registrationSecret="B" * 43))

    def test_disabled_installation_is_refused(self):
        self.bind()
        devices.unregister(self.payload())
        with self.assertRaises(PermissionError):
            mobile_wallet.status(self.payload())

    def test_payload_is_exact_and_does_not_accept_referral_code_as_identity(self):
        self.bind()
        with self.assertRaises(ValueError):
            mobile_wallet.status({**self.payload(), "referralCode": self.account["code"]})
        with self.assertRaises(ValueError):
            mobile_wallet.status({"referralCode": self.account["code"]})

    def test_multiple_owned_wallets_are_supported_without_internal_ids(self):
        self.bind()
        second = referrals.create_account("OWNER-9Q2M")
        self.bind(second)
        result = mobile_wallet.status(self.payload())
        self.assertEqual(result["walletCount"], 2)
        self.assertEqual(
            [wallet["referralCode"] for wallet in result["wallets"]],
            ["OWNER-7K4P", "OWNER-9Q2M"],
        )
        serialized = repr(result)
        self.assertNotIn(self.account["id"], serialized)
        self.assertNotIn(second["id"], serialized)

    def test_legacy_oversized_ownership_state_fails_closed(self):
        accounts = [self.account]
        for index in range(1, claims._MAX_WALLETS_PER_INSTALLATION + 1):
            accounts.append(referrals.create_account(f"LEG-{index:02d}-A"))
        installation_hash = hashlib.sha256(self.installation.encode()).hexdigest()
        with analytics.connect() as db:
            for index, account in enumerate(accounts):
                db.execute(
                    """INSERT INTO referral_wallet_owner(
                       account_id,installation_hash,claimed_at,evidence_hash
                       ) VALUES(?,?,?,?)""",
                    (
                        account["id"],
                        installation_hash,
                        f"2026-09-22T00:00:{index:02d}+00:00",
                        hashlib.sha256(f"legacy-{account['id']}".encode()).hexdigest(),
                    ),
                )
        with self.assertRaises(RuntimeError):
            mobile_wallet.status(self.payload())


if __name__ == "__main__":
    unittest.main()
