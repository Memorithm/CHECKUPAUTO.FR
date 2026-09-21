import datetime
import sqlite3
import tempfile
import unittest
from pathlib import Path

import analytics_store as analytics
import referral_engine as referrals
import referral_integrity_audit as audit


class ReferralLedgerCompactionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old_db = analytics.DB
        analytics.DB = Path(self.tmp.name) / "analytics.sqlite3"
        self.addCleanup(setattr, analytics, "DB", self.old_db)
        analytics.init_db()
        referrals.init_db()

    @staticmethod
    def old_iso(days=120):
        return (
            datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(days=days)
        ).isoformat(timespec="seconds")

    def earn(self, code, external_id):
        referrals.record_pending(code, "mercure-rdv", external_id, "intent-" + external_id)
        return referrals.complete_control("mercure-rdv", external_id)

    def age_ledger(self, account_id, days=120):
        with analytics.connect() as db:
            db.execute(
                "UPDATE referral_ledger SET created_at=? WHERE account_id=?",
                (self.old_iso(days), account_id),
            )

    def test_compaction_preserves_balance_and_duplicate_redemption_guard(self):
        account = referrals.create_account("COMPACT-01")
        self.earn(account["code"], "rdv-a")
        self.earn(account["code"], "rdv-b")
        referrals.redeem(account["code"], 400, "invoice-old")
        before = referrals.account_summary(account["code"])
        self.assertEqual(before["balanceCents"], 600)
        self.age_ledger(account["id"])

        result = referrals.compact_ledger(30)
        self.assertEqual(result["compactedEntries"], 3)
        self.assertEqual(result["netCents"], 600)

        after = referrals.account_summary(account["code"])
        self.assertEqual(after["balanceCents"], before["balanceCents"])
        self.assertEqual(after["compactedBalanceCents"], 600)
        self.assertEqual(after["compactedEntries"], 3)
        self.assertEqual(after["ledger"], [])
        with self.assertRaises(ValueError):
            referrals.redeem(account["code"], 1, "invoice-old")
        redeemed = referrals.redeem(account["code"], 500, "invoice-new")
        self.assertEqual(redeemed["balanceCents"], 100)

    def test_earned_reward_can_be_reversed_after_earn_is_compacted(self):
        account = referrals.create_account("COMPACT-REV")
        self.earn(account["code"], "rdv-reverse")
        self.age_ledger(account["id"])
        referrals.compact_ledger(30)
        with analytics.connect() as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) n FROM referral_ledger").fetchone()["n"],
                0,
            )
            evidence = db.execute(
                "SELECT reversed FROM referral_compacted_reward_evidence"
            ).fetchone()
            self.assertEqual(int(evidence["reversed"]), 0)

        reversed_reward = referrals.cancel_pending("mercure-rdv", "rdv-reverse")
        self.assertEqual(reversed_reward["status"], "reversed")
        summary = referrals.account_summary(account["code"])
        self.assertEqual(summary["balanceCents"], 0)
        self.assertEqual(
            [item["kind"] for item in summary["ledger"]],
            ["reverse"],
        )
        with analytics.connect() as db:
            evidence = db.execute(
                "SELECT reversed FROM referral_compacted_reward_evidence"
            ).fetchone()
            self.assertEqual(int(evidence["reversed"]), 1)

    def test_compacted_reverse_cannot_be_duplicated_by_direct_sql(self):
        account = referrals.create_account("COMPACT-TRIGGER")
        self.earn(account["code"], "rdv-trigger")
        self.age_ledger(account["id"])
        referrals.compact_ledger(30)
        referrals.cancel_pending("mercure-rdv", "rdv-trigger")
        self.age_ledger(account["id"])
        referrals.compact_ledger(30)
        reference = referrals._reward_ledger_reference("mercure-rdv", "rdv-trigger")
        with analytics.connect() as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) n FROM referral_ledger").fetchone()["n"],
                0,
            )
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute(
                    """INSERT INTO referral_ledger(
                         account_id,kind,amount_cents,reference,created_at,note
                       ) VALUES(?,?,?,?,?,?)""",
                    (
                        account["id"], "reverse", -500, reference,
                        referrals.now_iso(), "duplicate reverse",
                    ),
                )

    def test_integrity_audit_remains_green_after_compaction(self):
        account = referrals.create_account("COMPACT-AUDIT")
        self.earn(account["code"], "rdv-earned")
        self.earn(account["code"], "rdv-reversed")
        referrals.cancel_pending("mercure-rdv", "rdv-reversed")
        referrals.redeem(account["code"], 200, "invoice-audit")
        self.age_ledger(account["id"])
        referrals.compact_ledger(30)
        report = audit.status(analytics.DB)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["issues"], 0)
        self.assertGreaterEqual(report["metrics"]["compactedEarns"], 2)
        self.assertEqual(
            referrals.account_summary(account["code"])["balanceCents"],
            300,
        )

    def test_unambiguous_legacy_earn_is_canonicalized_during_compaction(self):
        account = referrals.create_account("COMPACT-LEGACY")
        reward = referrals.record_pending(
            account["code"], "mercure-rdv", "legacy-42", "legacy-intent"
        )
        old = self.old_iso()
        legacy = "mercure-rdv:legacy-42"
        with analytics.connect() as db:
            db.execute(
                """UPDATE referral_rewards
                   SET status='earned',earned_at=?,updated_at=?
                   WHERE provider='mercure-rdv' AND external_id='legacy-42'""",
                (old, old),
            )
            db.execute(
                """INSERT INTO referral_ledger(
                     account_id,kind,amount_cents,reference,created_at,note
                   ) VALUES(?,?,?,?,?,?)""",
                (reward["account_id"], "earn", 500, legacy, old, "legacy"),
            )
        referrals.compact_ledger(30)
        modern = referrals._reward_ledger_reference("mercure-rdv", "legacy-42")
        with analytics.connect() as db:
            evidence = db.execute(
                """SELECT reference,amount_cents FROM referral_compacted_reward_evidence
                   WHERE account_id=?""",
                (account["id"],),
            ).fetchone()
        self.assertEqual(evidence["reference"], modern)
        self.assertEqual(int(evidence["amount_cents"]), 500)
        reversed_reward = referrals.cancel_pending("mercure-rdv", "legacy-42")
        self.assertEqual(reversed_reward["status"], "reversed")
        self.assertEqual(referrals.account_summary(account["code"])["balanceCents"], 0)

    def test_ambiguous_legacy_reference_fails_closed_without_deletion(self):
        account = referrals.create_account("COMPACT-AMBIG")
        old = self.old_iso()
        pairs = (("mercure:rdv", "42"), ("mercure", "rdv:42"))
        self.assertEqual(
            referrals._legacy_reward_ledger_reference(*pairs[0]),
            referrals._legacy_reward_ledger_reference(*pairs[1]),
        )
        for idx, (provider, external) in enumerate(pairs):
            reward = referrals.record_pending(
                account["code"], provider, external, f"intent-{idx}"
            )
            with analytics.connect() as db:
                db.execute(
                    """UPDATE referral_rewards SET status='earned',earned_at=?,updated_at=?
                       WHERE provider=? AND external_id=?""",
                    (old, old, provider, external),
                )
                if idx == 0:
                    db.execute(
                        """INSERT INTO referral_ledger(
                             account_id,kind,amount_cents,reference,created_at,note
                           ) VALUES(?,?,?,?,?,?)""",
                        (
                            reward["account_id"], "earn", 500,
                            referrals._legacy_reward_ledger_reference(provider, external),
                            old, "ambiguous legacy",
                        ),
                    )
        with self.assertRaisesRegex(RuntimeError, "ambigu"):
            referrals.compact_ledger(30)
        with analytics.connect() as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) n FROM referral_ledger").fetchone()["n"],
                1,
            )


if __name__ == "__main__":
    unittest.main()
