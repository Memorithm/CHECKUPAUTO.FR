import tempfile
import unittest
from pathlib import Path

import analytics_store as analytics
import referral_engine as referrals


class ReferralLegacyReversalTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = analytics.DB
        analytics.DB = Path(self.tmp.name) / "analytics.sqlite3"
        analytics.init_db()
        referrals.init_db()
        self.account = referrals.create_account("LEGACY-REVERSAL")

    def tearDown(self):
        analytics.DB = self.old_db
        self.tmp.cleanup()

    def _legacy_earn(self, provider, external_id, token):
        reward = referrals.record_pending(
            self.account["code"], provider, external_id, token
        )
        now = referrals.now_iso()
        reference = f"{provider}:{external_id}"
        with analytics.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """UPDATE referral_rewards
                   SET status='earned',updated_at=?,earned_at=?
                   WHERE provider=? AND external_id=?""",
                (now, now, provider, external_id),
            )
            db.execute(
                """INSERT OR IGNORE INTO referral_ledger(
                   account_id,kind,amount_cents,reference,created_at,note
                   ) VALUES(?,?,?,?,?,?)""",
                (
                    reward["account_id"],
                    "earn",
                    int(reward["reward_cents"]),
                    reference,
                    now,
                    "legacy reward",
                ),
            )
        return reference

    def test_unambiguous_pre_hash_credit_can_still_be_reversed(self):
        legacy_reference = self._legacy_earn("mercure-rdv", "legacy-42", "legacy-token")
        self.assertEqual(referrals.account_summary(self.account["code"])["balanceCents"], 500)

        reversed_reward = referrals.cancel_pending("mercure-rdv", "legacy-42")
        self.assertEqual(reversed_reward["status"], "reversed")
        summary = referrals.account_summary(self.account["code"])
        self.assertEqual(summary["balanceCents"], 0)
        reverse_entries = [item for item in summary["ledger"] if item["kind"] == "reverse"]
        self.assertEqual(len(reverse_entries), 1)
        self.assertEqual(reverse_entries[0]["reference"], legacy_reference)
        self.assertEqual(reverse_entries[0]["amountCents"], -500)

    def test_ambiguous_legacy_collision_fails_closed_without_wallet_mutation(self):
        first_provider, first_external = "mercure:rdv", "42"
        second_provider, second_external = "mercure", "rdv:42"
        self.assertEqual(
            f"{first_provider}:{first_external}",
            f"{second_provider}:{second_external}",
        )
        self._legacy_earn(first_provider, first_external, "legacy-a")
        self._legacy_earn(second_provider, second_external, "legacy-b")
        self.assertEqual(referrals.account_summary(self.account["code"])["balanceCents"], 500)

        with self.assertRaisesRegex(RuntimeError, "historique.*ambigu"):
            referrals.cancel_pending(first_provider, first_external)

        first = referrals.reward_status(first_provider, first_external)
        second = referrals.reward_status(second_provider, second_external)
        self.assertEqual(first["status"], "earned")
        self.assertEqual(second["status"], "earned")
        summary = referrals.account_summary(self.account["code"])
        self.assertEqual(summary["balanceCents"], 500)
        self.assertEqual(
            [item for item in summary["ledger"] if item["kind"] == "reverse"],
            [],
        )


if __name__ == "__main__":
    unittest.main()
