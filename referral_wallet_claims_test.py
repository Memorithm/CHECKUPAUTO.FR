import hashlib
import tempfile
import unittest
from pathlib import Path

import analytics_store as analytics
import mobile_devices as devices
import referral_engine as referrals
import referral_wallet_claims as claims


class ReferralWalletClaimsTest(unittest.TestCase):
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

    def _consume(self, token, **changes):
        payload = {
            "installationId": self.installation,
            "registrationSecret": self.secret,
            "claimToken": token,
        }
        payload.update(changes)
        return claims.consume(payload)

    def test_issue_persists_only_token_hash(self):
        issued = claims.issue(self.account["code"])
        token = issued["claimToken"]
        self.assertGreaterEqual(len(token), 32)
        self.assertTrue(issued["singleUse"])
        self.assertFalse(issued["rawTokenPersisted"])
        with analytics.connect() as db:
            row = db.execute(
                "SELECT token_hash,account_id FROM referral_wallet_claim"
            ).fetchone()
        self.assertEqual(row["token_hash"], hashlib.sha256(token.encode()).hexdigest())
        self.assertEqual(row["account_id"], self.account["id"])
        self.assertNotEqual(row["token_hash"], token)

    def test_authenticated_mobile_claim_binds_wallet_without_raw_installation(self):
        token = claims.issue(self.account["code"])["claimToken"]
        result = self._consume(token)
        self.assertTrue(result["ok"])
        self.assertEqual(result["accountId"], self.account["id"])
        self.assertEqual(result["provenance"], "authenticated_mobile_wallet_claim")
        self.assertTrue(claims.ownership_matches(self.account["id"], self.installation))
        with analytics.connect() as db:
            owner = db.execute(
                "SELECT installation_hash,evidence_hash FROM referral_wallet_owner WHERE account_id=?",
                (self.account["id"],),
            ).fetchone()
            pending = db.execute("SELECT COUNT(*) n FROM referral_wallet_claim").fetchone()["n"]
        self.assertEqual(
            owner["installation_hash"],
            hashlib.sha256(self.installation.encode()).hexdigest(),
        )
        self.assertNotEqual(owner["installation_hash"], self.installation)
        self.assertRegex(owner["evidence_hash"], r"^[0-9a-f]{64}$")
        self.assertEqual(pending, 0)

    def test_claim_is_single_use(self):
        token = claims.issue(self.account["code"])["claimToken"]
        self._consume(token)
        with self.assertRaises(PermissionError):
            self._consume(token)

    def test_wrong_registration_secret_cannot_consume_claim(self):
        token = claims.issue(self.account["code"])["claimToken"]
        with self.assertRaises(PermissionError):
            self._consume(token, registrationSecret="B" * 43)
        result = self._consume(token)
        self.assertTrue(result["ok"])

    def test_shareable_referral_code_is_not_sufficient_to_claim_wallet(self):
        issued = claims.issue(self.account["code"])
        with self.assertRaises(ValueError):
            claims.consume({
                "installationId": self.installation,
                "registrationSecret": self.secret,
                "claimToken": self.account["code"],
            })
        self.assertTrue(self._consume(issued["claimToken"])["ok"])

    def test_second_installation_cannot_take_over_bound_wallet(self):
        first_token = claims.issue(self.account["code"])["claimToken"]
        self._consume(first_token)
        other_installation = "4fb1e2f8-fd94-49af-8642-b6aad6f6c721"
        other_secret = "C" * 43
        devices.register_installation({
            "installationId": other_installation,
            "registrationSecret": other_secret,
        })
        second_token = claims.issue(self.account["code"])["claimToken"]
        with self.assertRaises(PermissionError):
            claims.consume({
                "installationId": other_installation,
                "registrationSecret": other_secret,
                "claimToken": second_token,
            })
        self.assertTrue(claims.ownership_matches(self.account["id"], self.installation))
        self.assertFalse(claims.ownership_matches(self.account["id"], other_installation))

    def test_disabled_installation_cannot_claim_wallet(self):
        token = claims.issue(self.account["code"])["claimToken"]
        devices.unregister({
            "installationId": self.installation,
            "registrationSecret": self.secret,
        })
        with self.assertRaises(PermissionError):
            self._consume(token)

    def test_expired_claim_is_rejected_and_removed(self):
        token = claims.issue(self.account["code"])["claimToken"]
        with analytics.connect() as db:
            db.execute(
                "UPDATE referral_wallet_claim SET expires_at='2000-01-01T00:00:00+00:00'"
            )
        with self.assertRaises(PermissionError):
            self._consume(token)
        with analytics.connect() as db:
            count = db.execute("SELECT COUNT(*) n FROM referral_wallet_claim").fetchone()["n"]
        self.assertEqual(count, 0)

    def test_new_claim_revokes_previous_pending_claim(self):
        first = claims.issue(self.account["code"])["claimToken"]
        second = claims.issue(self.account["code"])["claimToken"]
        with self.assertRaises(PermissionError):
            self._consume(first)
        self.assertTrue(self._consume(second)["ok"])

    def test_capability_exposes_counts_without_owner_identifiers(self):
        token = claims.issue(self.account["code"])["claimToken"]
        before = claims.capability()
        self.assertEqual(before["liveClaimCount"], 1)
        self.assertEqual(before["ownerEvidenceCount"], 0)
        self.assertNotIn(self.account["id"], str(before))
        self.assertNotIn(self.installation, str(before))
        self._consume(token)
        after = claims.capability()
        self.assertEqual(after["liveClaimCount"], 0)
        self.assertEqual(after["ownerEvidenceCount"], 1)
        self.assertEqual(after["claimEntropyBits"], 256)
        self.assertNotIn(self.account["id"], str(after))
        self.assertNotIn(self.installation, str(after))


if __name__ == "__main__":
    unittest.main()
