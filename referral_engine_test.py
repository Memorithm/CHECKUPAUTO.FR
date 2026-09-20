import sqlite3
import tempfile
import threading
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

    def test_earn_reference_cannot_collide_across_provider_external_id_boundaries(self):
        account = referrals.create_account("BOUNDARY-1")
        first_provider, first_external = "mercure:rdv", "42"
        second_provider, second_external = "mercure", "rdv:42"
        self.assertEqual(
            f"{first_provider}:{first_external}",
            f"{second_provider}:{second_external}",
        )
        referrals.record_pending(account["code"], first_provider, first_external, "intent-a")
        referrals.record_pending(account["code"], second_provider, second_external, "intent-b")
        referrals.complete_control(first_provider, first_external)
        referrals.complete_control(second_provider, second_external)

        summary = referrals.account_summary(account["code"])
        earn_entries = [entry for entry in summary["ledger"] if entry["kind"] == "earn"]
        self.assertEqual(summary["earnedReferrals"], 2)
        self.assertEqual(summary["balanceCents"], 1000)
        self.assertEqual(len(earn_entries), 2)
        self.assertEqual(len({entry["reference"] for entry in earn_entries}), 2)
        for entry in earn_entries:
            self.assertRegex(entry["reference"], r"^reward:[0-9a-f]{64}$")
            self.assertNotIn("mercure", entry["reference"])
            self.assertNotIn("rdv", entry["reference"])

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

    def test_concurrent_redemptions_cannot_overdraw_wallet(self):
        account = referrals.create_account("RACE-100")
        referrals.record_pending(account["code"], "mercure-rdv", "rdv-race", "intent-race")
        referrals.complete_control("mercure-rdv", "rdv-race")

        barrier = threading.Barrier(2)
        results = []
        lock = threading.Lock()

        def redeem(reference):
            barrier.wait()
            try:
                result = referrals.redeem(account["code"], 400, reference)
                outcome = ("ok", result["balanceCents"])
            except ValueError as exc:
                outcome = ("error", str(exc))
            with lock:
                results.append(outcome)

        threads = [
            threading.Thread(target=redeem, args=("race-a",)),
            threading.Thread(target=redeem, args=("race-b",)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertEqual(len(results), 2)
        self.assertEqual(sum(1 for status, _ in results if status == "ok"), 1)
        self.assertEqual(sum(1 for status, _ in results if status == "error"), 1)
        self.assertEqual(referrals.account_summary(account["code"])["balanceCents"], 100)

    def test_ledger_trigger_rejects_direct_negative_balance(self):
        account = referrals.create_account("TRIGGER-1")
        with analytics.connect() as db:
            row = db.execute(
                "SELECT id FROM referral_accounts WHERE code=?",
                (account["code"],),
            ).fetchone()
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute(
                    """INSERT INTO referral_ledger(
                       account_id,kind,amount_cents,reference,created_at,note
                       ) VALUES(?,?,?,?,?,?)""",
                    (row["id"], "redeem", -100, "manual-overdraw", referrals.now_iso(), "test"),
                )

    def test_completion_and_cancellation_cannot_diverge_reward_and_ledger(self):
        account = referrals.create_account("STATE-RACE")
        referrals.record_pending(account["code"], "mercure-rdv", "rdv-state-race", "intent-state-race")
        barrier = threading.Barrier(2)
        errors = []
        lock = threading.Lock()

        def run(action):
            barrier.wait()
            try:
                action("mercure-rdv", "rdv-state-race")
            except Exception as exc:  # surfaced below so thread failures cannot be lost
                with lock:
                    errors.append(exc)

        threads = [
            threading.Thread(target=run, args=(referrals.complete_control,)),
            threading.Thread(target=run, args=(referrals.cancel_pending,)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertEqual(errors, [])
        reward = referrals.reward_status("mercure-rdv", "rdv-state-race")
        summary = referrals.account_summary(account["code"])
        self.assertIn(reward["status"], {"earned", "cancelled", "reversed"})
        expected_balance = 500 if reward["status"] == "earned" else 0
        self.assertEqual(summary["balanceCents"], expected_balance)

    def test_unknown_referral_code_is_not_attributed(self):
        self.assertEqual(referrals.valid_code_or_empty("UNKNOWN-1"), "")
        self.assertIsNone(referrals.record_pending("UNKNOWN-1", "mercure-rdv", "rdv-x", "intent-x"))


if __name__ == "__main__":
    unittest.main()
