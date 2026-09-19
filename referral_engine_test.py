import tempfile
import unittest
from pathlib import Path

import analytics_store as analytics
import referral_engine as referrals


class ReferralEngineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = analytics.DB
        analytics.DB = Path(self.tmp.name) / "analytics.sqlite3"
        analytics.init_db()
        referrals.init_db()

    def tearDown(self):
        analytics.DB = self.old_db
        self.tmp.cleanup()

    def test_creates_shareable_code_with_five_euro_default(self):
        account = referrals.create_account()
        self.assertTrue(account["code"].startswith("CA-"))
        self.assertEqual(account["rewardCents"], 500)
        self.assertEqual(account["balanceCents"], 0)

    def test_reward_is_pending_until_completed_control(self):
        account = referrals.create_account("MARC-7K4P")
        pending = referrals.record_pending(account["code"], "mercure-rdv", "rdv-42", "intent-1")
        self.assertEqual(pending["status"], "pending")
        self.assertEqual(referrals.account_summary(account["code"])["balanceCents"], 0)
        self.assertEqual(referrals.account_summary(account["code"])["pendingCents"], 500)
        earned = referrals.complete_control("mercure-rdv", "rdv-42")
        self.assertEqual(earned["status"], "earned")
        summary = referrals.account_summary(account["code"])
        self.assertEqual(summary["balanceCents"], 500)
        self.assertEqual(summary["earnedReferrals"], 1)

    def test_completion_is_idempotent(self):
        account = referrals.create_account("TAREK-7K4P")
        referrals.record_pending(account["code"], "mercure-rdv", "rdv-1", "intent-1")
        referrals.complete_control("mercure-rdv", "rdv-1")
        referrals.complete_control("mercure-rdv", "rdv-1")
        summary = referrals.account_summary(account["code"])
        self.assertEqual(summary["balanceCents"], 500)
        self.assertEqual(len([x for x in summary["ledger"] if x["kind"] == "earn"]), 1)

    def test_cancelled_booking_never_earns_credit(self):
        account = referrals.create_account("CLIENT-123")
        referrals.record_pending(account["code"], "mercure-rdv", "rdv-2", "intent-2")
        cancelled = referrals.cancel_pending("mercure-rdv", "rdv-2")
        self.assertEqual(cancelled["status"], "cancelled")
        result = referrals.complete_control("mercure-rdv", "rdv-2")
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(referrals.account_summary(account["code"])["balanceCents"], 0)

    def test_provider_id_replaces_browser_placeholder_for_same_intent(self):
        account = referrals.create_account("CLIENT-456")
        first = referrals.record_pending(account["code"], "mercure-rdv", "browser-placeholder", "intent-9")
        self.assertEqual(first["external_id"], "browser-placeholder")
        second = referrals.record_pending(account["code"], "mercure-rdv", "mercure-9001", "intent-9")
        self.assertEqual(second["external_id"], "mercure-9001")
        referrals.complete_control("mercure-rdv", "mercure-9001")
        self.assertEqual(referrals.account_summary(account["code"])["balanceCents"], 500)

    def test_credit_can_be_redeemed_but_not_overdrawn(self):
        account = referrals.create_account("CLIENT-789")
        for idx in range(3):
            external = f"rdv-{idx}"
            token = f"intent-{idx}"
            referrals.record_pending(account["code"], "mercure-rdv", external, token)
            referrals.complete_control("mercure-rdv", external)
        summary = referrals.redeem(account["code"], 1000, "control-2027")
        self.assertEqual(summary["balanceCents"], 500)
        with self.assertRaises(ValueError):
            referrals.redeem(account["code"], 600, "control-2028")

    def test_unknown_referral_code_is_not_attributed(self):
        self.assertEqual(referrals.valid_code_or_empty("UNKNOWN-1"), "")
        self.assertIsNone(referrals.record_pending("UNKNOWN-1", "mercure-rdv", "rdv-x", "intent-x"))


if __name__ == "__main__":
    unittest.main()
