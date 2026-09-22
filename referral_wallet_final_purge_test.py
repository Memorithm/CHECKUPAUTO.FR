import datetime
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import analytics_store as analytics
import compliance_store
import referral_engine
import referral_wallet_claims
import referral_wallet_final_purge as final_purge
import retention_enforcement


class ReferralWalletFinalPurgeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old_analytics = analytics.DB
        self.old_compliance = compliance_store.DB
        analytics.DB = Path(self.tmp.name) / "analytics.sqlite3"
        compliance_store.DB = Path(self.tmp.name) / "compliance.sqlite3"
        self.addCleanup(setattr, analytics, "DB", self.old_analytics)
        self.addCleanup(setattr, compliance_store, "DB", self.old_compliance)
        analytics.init_db()
        referral_engine.init_db()
        referral_wallet_claims.init_db()
        compliance_store.init_db()
        self.now = datetime.datetime(2026, 9, 22, 20, 0, tzinfo=datetime.timezone.utc)

    def retire(self, account_id):
        with analytics.connect() as db:
            db.execute(
                "UPDATE referral_accounts SET active=0,code=? WHERE id=?",
                (final_purge._retired_code(account_id), account_id),
            )

    def test_empty_retired_wallet_is_physically_deleted(self):
        account = referral_engine.create_account("PURGE-EMPTY")
        self.retire(account["id"])

        result = final_purge.purge_retired_wallets(30, now=self.now)

        self.assertTrue(result["ok"])
        self.assertEqual(result["purgedAccounts"], 1)
        self.assertEqual(result["purgedRows"], 1)
        self.assertFalse(result["rawAccountIdentifiersPersisted"])
        with analytics.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) n FROM referral_accounts").fetchone()["n"], 0)
        with compliance_store.connect() as db:
            row = db.execute(
                "SELECT account_hash,state,evidence_hash FROM referral_wallet_final_purge_audit"
            ).fetchone()
        self.assertEqual(row["state"], "completed")
        self.assertEqual(len(row["account_hash"]), 64)
        self.assertEqual(len(row["evidence_hash"]), 64)
        self.assertNotIn(account["id"], str(dict(row)))

    def test_dry_run_has_no_mutation_or_audit_side_effect(self):
        account = referral_engine.create_account("PURGE-DRY")
        self.retire(account["id"])

        result = final_purge.purge_retired_wallets(30, now=self.now, dry_run=True)

        self.assertEqual(result["eligibleAccounts"], 1)
        self.assertEqual(result["purgedAccounts"], 0)
        with analytics.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) n FROM referral_accounts").fetchone()["n"], 1)
        final_purge._init_audit()
        with compliance_store.connect() as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) n FROM referral_wallet_final_purge_audit").fetchone()["n"],
                0,
            )

    def test_recent_terminal_reward_blocks_purge_until_retention_expires(self):
        account = referral_engine.create_account("PURGE-REWARD")
        referral_engine.record_pending(account["code"], "mercure-rdv", "rdv-private", "intent-private")
        referral_engine.cancel_pending("mercure-rdv", "rdv-private")
        self.retire(account["id"])

        first = final_purge.purge_retired_wallets(30, now=self.now, dry_run=True)
        self.assertEqual(first["eligibleAccounts"], 0)

        old = (self.now - datetime.timedelta(days=60)).isoformat(timespec="seconds")
        with analytics.connect() as db:
            db.execute(
                "UPDATE referral_rewards SET updated_at=?,cancelled_at=? WHERE account_id=?",
                (old, old, account["id"]),
            )
        second = final_purge.purge_retired_wallets(30, now=self.now)
        self.assertEqual(second["purgedAccounts"], 1)
        with analytics.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) n FROM referral_rewards").fetchone()["n"], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) n FROM referral_accounts").fetchone()["n"], 0)

    def test_live_ledger_and_recent_compaction_fail_closed(self):
        account = referral_engine.create_account("PURGE-LEDGER")
        referral_engine.record_pending(account["code"], "mercure-rdv", "rdv-earned", "intent-earned")
        referral_engine.complete_control("mercure-rdv", "rdv-earned")
        referral_engine.cancel_pending("mercure-rdv", "rdv-earned")
        self.retire(account["id"])
        old = (self.now - datetime.timedelta(days=60)).isoformat(timespec="seconds")
        with analytics.connect() as db:
            db.execute("UPDATE referral_rewards SET updated_at=?,reversed_at=? WHERE account_id=?", (old, old, account["id"]))
            db.execute("UPDATE referral_ledger SET created_at=? WHERE account_id=?", (old, account["id"]))

        self.assertEqual(
            final_purge.purge_retired_wallets(30, now=self.now, dry_run=True)["eligibleAccounts"],
            0,
        )
        compacted = referral_engine.compact_ledger(30, now=self.now)
        self.assertGreater(compacted["compactedEntries"], 0)
        self.assertEqual(
            final_purge.purge_retired_wallets(30, now=self.now, dry_run=True)["eligibleAccounts"],
            0,
        )

        with analytics.connect() as db:
            db.execute(
                "UPDATE referral_ledger_checkpoint SET updated_at=? WHERE account_id=?",
                (old, account["id"]),
            )
            db.execute(
                "UPDATE referral_compacted_reward_evidence SET compacted_at=? WHERE account_id=?",
                (old, account["id"]),
            )
        done = final_purge.purge_retired_wallets(30, now=self.now)
        self.assertEqual(done["purgedAccounts"], 1)

    def test_owner_evidence_blocks_final_purge(self):
        account = referral_engine.create_account("PURGE-OWNER")
        self.retire(account["id"])
        with analytics.connect() as db:
            db.execute(
                """INSERT INTO referral_wallet_owner(account_id,installation_hash,claimed_at)
                   VALUES(?,?,?)""",
                (account["id"], "a" * 64, self.now.isoformat(timespec="seconds")),
            )
        result = final_purge.purge_retired_wallets(30, now=self.now, dry_run=True)
        self.assertEqual(result["eligibleAccounts"], 0)

    def test_planned_audit_is_recovered_after_post_commit_failure(self):
        account = referral_engine.create_account("PURGE-RECOVER")
        self.retire(account["id"])
        with mock.patch.object(final_purge, "_complete", side_effect=RuntimeError("simulated audit outage")):
            with self.assertRaisesRegex(RuntimeError, "audit outage"):
                final_purge.purge_retired_wallets(30, now=self.now)
        with analytics.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) n FROM referral_accounts").fetchone()["n"], 0)
        with compliance_store.connect() as db:
            self.assertEqual(
                db.execute("SELECT state FROM referral_wallet_final_purge_audit").fetchone()["state"],
                "planned",
            )

        recovered = final_purge.purge_retired_wallets(30, now=self.now)
        self.assertEqual(recovered["recoveredPlannedOperations"], 1)
        with compliance_store.connect() as db:
            row = db.execute(
                "SELECT state,purged_rows FROM referral_wallet_final_purge_audit"
            ).fetchone()
        self.assertEqual(row["state"], "recovered_absent")
        self.assertEqual(int(row["purged_rows"]), 1)

    def test_run_policy_requires_legally_reviewed_configuration(self):
        account = referral_engine.create_account("PURGE-POLICY")
        self.retire(account["id"])
        with self.assertRaisesRegex(RuntimeError, "politique"):
            final_purge.run_policy(now=self.now)

        retention_enforcement.save_policy(
            {
                "ruleId": "referral_ledger",
                "activeDays": 30,
                "justification": "Durée validée par la revue juridique de test.",
                "legalReviewConfirmed": True,
                "enabled": True,
            }
        )
        result = final_purge.run_policy(now=self.now)
        self.assertEqual(result["ruleId"], "referral_ledger")
        self.assertTrue(result["legalReviewConfirmed"])
        self.assertEqual(result["purgedAccounts"], 1)


if __name__ == "__main__":
    unittest.main()
