import sqlite3
import tempfile
import unittest
from pathlib import Path

import analytics_store as analytics
import booking_bridge as booking
import referral_engine as referrals


class ReferralReversalTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.old_db = analytics.DB
        self.old_secret = booking.SECRET_FILE
        analytics.DB = root / "analytics.sqlite3"
        booking.SECRET_FILE = root / "mercure-webhook-secret"
        analytics.init_db()
        booking.init_db()
        self.account = referrals.create_account("REVERSAL-01")

    def tearDown(self):
        analytics.DB = self.old_db
        booking.SECRET_FILE = self.old_secret
        self.tmp.cleanup()

    def intent(self):
        return booking.create_intent(
            {
                "device": "mobile",
                "path": "/",
                "service": "Contrôle technique",
                "referralCode": self.account["code"],
            },
            "https://rdv.checkupauto.fr/",
        )

    def complete(self, external_id="rdv-reversal"):
        intent = self.intent()
        return booking.apply_conversion(
            {
                "externalId": external_id,
                "status": "completed",
                "ccid": intent["token"],
                "service": "Contrôle technique",
                "amount": 80,
            }
        )

    def test_late_cancellation_reverses_earned_credit_idempotently(self):
        self.complete()
        self.assertEqual(referrals.account_summary(self.account["code"])["balanceCents"], 500)

        first = booking.apply_conversion(
            {"externalId": "rdv-reversal", "status": "cancelled"}
        )
        self.assertEqual(first["referralStatus"], "reversed")
        summary = referrals.account_summary(self.account["code"])
        self.assertEqual(summary["balanceCents"], 0)
        self.assertEqual(summary["earnedReferrals"], 0)
        self.assertEqual(summary["reversedReferrals"], 1)
        reversals = [entry for entry in summary["ledger"] if entry["kind"] == "reverse"]
        self.assertEqual(len(reversals), 1)
        self.assertEqual(reversals[0]["amountCents"], -500)
        self.assertRegex(reversals[0]["reference"], r"^reward:[0-9a-f]{64}$")

        second = booking.apply_conversion(
            {"externalId": "rdv-reversal", "status": "cancelled"}
        )
        self.assertEqual(second["referralStatus"], "reversed")
        summary = referrals.account_summary(self.account["code"])
        self.assertEqual(
            len([entry for entry in summary["ledger"] if entry["kind"] == "reverse"]),
            1,
        )

    def test_late_no_show_after_spend_records_debt_and_blocks_more_redemption(self):
        self.complete("rdv-spent")
        referrals.redeem(self.account["code"], 400, "invoice-before-correction")
        self.assertEqual(referrals.account_summary(self.account["code"])["balanceCents"], 100)

        corrected = booking.apply_conversion(
            {"externalId": "rdv-spent", "status": "no_show"}
        )
        self.assertEqual(corrected["referralStatus"], "reversed")
        summary = referrals.account_summary(self.account["code"])
        self.assertEqual(summary["balanceCents"], -400)
        self.assertEqual(summary["reversedReferrals"], 1)
        with self.assertRaises(ValueError):
            referrals.redeem(self.account["code"], 1, "invoice-blocked-by-debt")

    def test_reverse_ledger_entry_cannot_exist_without_matching_earn(self):
        with analytics.connect() as db:
            account_id = db.execute(
                "SELECT id FROM referral_accounts WHERE code=?",
                (self.account["code"],),
            ).fetchone()["id"]
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute(
                    """INSERT INTO referral_ledger(
                       account_id,kind,amount_cents,reference,created_at,note
                       ) VALUES(?,?,?,?,?,?)""",
                    (
                        account_id,
                        "reverse",
                        -500,
                        "reward:" + "0" * 64,
                        referrals.now_iso(),
                        "invalid reversal",
                    ),
                )

    def test_pending_cancellation_still_never_creates_negative_ledger_entry(self):
        intent = self.intent()
        booking.apply_conversion(
            {
                "externalId": "rdv-pending",
                "status": "confirmed",
                "ccid": intent["token"],
            }
        )
        result = booking.apply_conversion(
            {"externalId": "rdv-pending", "status": "cancelled"}
        )
        self.assertEqual(result["referralStatus"], "cancelled")
        summary = referrals.account_summary(self.account["code"])
        self.assertEqual(summary["balanceCents"], 0)
        self.assertEqual(
            [entry for entry in summary["ledger"] if entry["kind"] == "reverse"],
            [],
        )


if __name__ == "__main__":
    unittest.main()
