import json
import tempfile
import unittest
from pathlib import Path

import analytics_store as analytics
import referral_engine as referrals
import referral_integrity_audit as audit


class ReferralIntegrityAuditTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = analytics.DB
        analytics.DB = Path(self.tmp.name) / "analytics.sqlite3"
        analytics.init_db()
        referrals.init_db()
        self.account = referrals.create_account("AUDIT-LEDGER")

    def tearDown(self):
        analytics.DB = self.old_db
        self.tmp.cleanup()

    def _legacy_earn(self, provider, external_id, token):
        reward = referrals.record_pending(self.account["code"], provider, external_id, token)
        now = referrals.now_iso()
        reference = referrals._legacy_reward_ledger_reference(provider, external_id)
        with analytics.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """UPDATE referral_rewards SET status='earned',updated_at=?,earned_at=?
                   WHERE provider=? AND external_id=?""",
                (now, now, provider, external_id),
            )
            db.execute(
                """INSERT OR IGNORE INTO referral_ledger(
                   account_id,kind,amount_cents,reference,created_at,note
                   ) VALUES(?,?,?,?,?,?)""",
                (reward["account_id"], "earn", int(reward["reward_cents"]), reference, now, "legacy audit fixture"),
            )
        return reward

    def test_healthy_modern_credit_and_reversal_are_ready(self):
        referrals.record_pending(self.account["code"], "mercure-rdv", "audit-modern", "audit-modern-token")
        referrals.complete_control("mercure-rdv", "audit-modern")
        ready = audit.status(analytics.DB)
        self.assertTrue(ready["ok"])
        self.assertEqual(ready["metrics"]["modernEarns"], 1)
        self.assertEqual(ready["issues"], 0)

        referrals.cancel_pending("mercure-rdv", "audit-modern")
        reversed_report = audit.status(analytics.DB)
        self.assertTrue(reversed_report["ok"])
        self.assertEqual(reversed_report["metrics"]["reversedRewards"], 1)
        self.assertEqual(reversed_report["metrics"]["missingReversals"], 0)

    def test_ambiguous_legacy_collision_is_reported_without_identifiers(self):
        first = ("mercure:rdv", "42", "legacy-a")
        second = ("mercure", "rdv:42", "legacy-b")
        self.assertEqual(
            referrals._legacy_reward_ledger_reference(first[0], first[1]),
            referrals._legacy_reward_ledger_reference(second[0], second[1]),
        )
        self._legacy_earn(*first)
        self._legacy_earn(*second)

        report = audit.status(analytics.DB)
        encoded = json.dumps(report, sort_keys=True)
        self.assertFalse(report["ok"])
        self.assertEqual(report["metrics"]["ambiguousLegacyReferences"], 1)
        self.assertNotIn("mercure:rdv", encoded)
        self.assertNotIn("rdv:42", encoded)
        self.assertNotIn("legacy-a", encoded)

    def test_missing_earn_is_detected(self):
        reward = referrals.record_pending(self.account["code"], "mercure-rdv", "missing-credit", "missing-token")
        now = referrals.now_iso()
        with analytics.connect() as db:
            db.execute(
                """UPDATE referral_rewards SET status='earned',updated_at=?,earned_at=?
                   WHERE provider=? AND external_id=?""",
                (now, now, reward["provider"], reward["external_id"]),
            )
        report = audit.status(analytics.DB)
        self.assertFalse(report["ok"])
        self.assertEqual(report["metrics"]["missingEarns"], 1)

    def test_orphan_earn_is_detected(self):
        account_id = self.account["id"]
        with analytics.connect() as db:
            db.execute(
                """INSERT INTO referral_ledger(account_id,kind,amount_cents,reference,created_at,note)
                   VALUES(?,?,?,?,?,?)""",
                (account_id, "earn", 500, "reward:" + "0" * 64, referrals.now_iso(), "synthetic orphan"),
            )
        report = audit.status(analytics.DB)
        self.assertFalse(report["ok"])
        self.assertEqual(report["metrics"]["orphanEarns"], 1)

    def test_duplicate_legacy_and_modern_earn_is_detected(self):
        provider = "mercure-rdv"
        external_id = "double-credit"
        reward = referrals.record_pending(self.account["code"], provider, external_id, "double-token")
        referrals.complete_control(provider, external_id)
        with analytics.connect() as db:
            db.execute(
                """INSERT INTO referral_ledger(account_id,kind,amount_cents,reference,created_at,note)
                   VALUES(?,?,?,?,?,?)""",
                (
                    reward["account_id"],
                    "earn",
                    int(reward["reward_cents"]),
                    referrals._legacy_reward_ledger_reference(provider, external_id),
                    referrals.now_iso(),
                    "synthetic duplicate",
                ),
            )
        report = audit.status(analytics.DB)
        self.assertFalse(report["ok"])
        self.assertEqual(report["metrics"]["duplicateEarnReferences"], 1)

    def test_missing_database_fails_closed_without_creating_file(self):
        missing = Path(self.tmp.name) / "does-not-exist.sqlite3"
        with self.assertRaisesRegex(audit.ReferralAuditUnavailable, "referral_ledger_unavailable"):
            audit.status(missing)
        self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()
