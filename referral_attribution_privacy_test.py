import re
import tempfile
import unittest
from pathlib import Path

import analytics_store as analytics
import referral_engine as referrals


class ReferralAttributionPrivacyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = analytics.DB
        analytics.DB = Path(self.tmp.name) / "analytics.sqlite3"
        analytics.init_db()
        referrals.init_db()

    def tearDown(self):
        analytics.DB = self.old_db
        self.tmp.cleanup()

    def _account_id(self, code):
        with analytics.connect() as db:
            row = db.execute(
                "SELECT id FROM referral_accounts WHERE code=?",
                (code,),
            ).fetchone()
        return row["id"]

    def test_new_rewards_persist_only_derived_attribution_key(self):
        account = referrals.create_account("PRIVACY-KEY")
        raw_token = "intent-private-browser-token"
        reward = referrals.record_pending(
            account["code"], "mercure-rdv", "browser-placeholder", raw_token
        )

        self.assertEqual(reward["status"], "pending")
        with analytics.connect() as db:
            row = db.execute(
                "SELECT attribution_token FROM referral_rewards WHERE provider=? AND external_id=?",
                ("mercure-rdv", "browser-placeholder"),
            ).fetchone()

        stored = str(row["attribution_token"])
        self.assertNotEqual(stored, raw_token)
        self.assertRegex(stored, r"^sha256-v1:[0-9a-f]{64}$")
        self.assertNotIn(raw_token, stored)

    def test_legacy_raw_token_is_migrated_and_replay_still_rebinds_provider_id(self):
        account = referrals.create_account("PRIVACY-MIGRATE")
        account_id = self._account_id(account["code"])
        raw_token = "legacy-intent-token"
        now = referrals.now_iso()
        with analytics.connect() as db:
            db.execute(
                "DELETE FROM referral_schema_meta WHERE key='attribution_token_storage'"
            )
            db.execute(
                """INSERT INTO referral_rewards(
                   provider,external_id,account_id,referral_code,status,reward_cents,
                   attribution_token,created_at,updated_at
                   ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    "mercure-rdv",
                    "browser-placeholder",
                    account_id,
                    account["code"],
                    "pending",
                    500,
                    raw_token,
                    now,
                    now,
                ),
            )

        referrals.init_db()
        with analytics.connect() as db:
            row = db.execute(
                "SELECT attribution_token FROM referral_rewards WHERE provider=? AND external_id=?",
                ("mercure-rdv", "browser-placeholder"),
            ).fetchone()
            marker = db.execute(
                "SELECT value FROM referral_schema_meta WHERE key='attribution_token_storage'"
            ).fetchone()
        self.assertRegex(str(row["attribution_token"]), r"^sha256-v1:[0-9a-f]{64}$")
        self.assertNotEqual(row["attribution_token"], raw_token)
        self.assertEqual(marker["value"], "sha256-v1")

        rebound = referrals.record_pending(
            account["code"], "mercure-rdv", "mercure-9001", raw_token
        )
        self.assertEqual(rebound["external_id"], "mercure-9001")
        self.assertEqual(rebound["status"], "pending")

    def test_migration_is_idempotent_and_repairs_raw_rows_from_rolling_deploy(self):
        account = referrals.create_account("PRIVACY-ROLL")
        account_id = self._account_id(account["code"])
        now = referrals.now_iso()
        raw_token = "old-process-token"
        with analytics.connect() as db:
            db.execute(
                """INSERT INTO referral_rewards(
                   provider,external_id,account_id,referral_code,status,reward_cents,
                   attribution_token,created_at,updated_at
                   ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    "mercure-rdv",
                    "rolling-rdv",
                    account_id,
                    account["code"],
                    "pending",
                    500,
                    raw_token,
                    now,
                    now,
                ),
            )

        referrals.init_db()
        with analytics.connect() as db:
            first = db.execute(
                "SELECT attribution_token FROM referral_rewards WHERE provider=? AND external_id=?",
                ("mercure-rdv", "rolling-rdv"),
            ).fetchone()["attribution_token"]
        referrals.init_db()
        with analytics.connect() as db:
            second = db.execute(
                "SELECT attribution_token FROM referral_rewards WHERE provider=? AND external_id=?",
                ("mercure-rdv", "rolling-rdv"),
            ).fetchone()["attribution_token"]
        self.assertEqual(first, second)
        self.assertRegex(str(second), r"^sha256-v1:[0-9a-f]{64}$")

    def test_earned_reward_cannot_be_rebound_or_credited_twice_by_token_replay(self):
        account = referrals.create_account("PRIVACY-EARN")
        raw_token = "intent-earned-once"
        referrals.record_pending(
            account["code"], "mercure-rdv", "browser-placeholder", raw_token
        )
        referrals.record_pending(
            account["code"], "mercure-rdv", "mercure-9002", raw_token
        )
        referrals.complete_control("mercure-rdv", "mercure-9002")

        replay = referrals.record_pending(
            account["code"], "mercure-rdv", "mercure-9003", raw_token
        )
        self.assertEqual(replay["external_id"], "mercure-9002")
        self.assertEqual(replay["status"], "earned")
        self.assertIsNone(referrals.complete_control("mercure-rdv", "mercure-9003"))

        summary = referrals.account_summary(account["code"])
        self.assertEqual(summary["earnedReferrals"], 1)
        self.assertEqual(summary["balanceCents"], 500)
        self.assertEqual(
            len([entry for entry in summary["ledger"] if entry["kind"] == "earn"]),
            1,
        )


if __name__ == "__main__":
    unittest.main()
