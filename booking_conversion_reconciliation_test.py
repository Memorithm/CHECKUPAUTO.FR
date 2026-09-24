import tempfile
import unittest
from pathlib import Path

import analytics_store as analytics
import booking_bridge as booking
import referral_engine as referrals


class BookingConversionReconciliationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.old_db = analytics.DB
        self.old_secret = booking.SECRET_FILE
        analytics.DB = root / "analytics.sqlite3"
        booking.SECRET_FILE = root / "mercure-webhook-secret"
        analytics.init_db()
        booking.init_db()

    def tearDown(self):
        analytics.DB = self.old_db
        booking.SECRET_FILE = self.old_secret
        self.tmp.cleanup()

    def intent(self, referral_code=""):
        return booking.create_intent(
            {
                "referrer": "https://www.google.com/",
                "utmSource": "google",
                "utmCampaign": "ct-local",
                "device": "mobile",
                "path": "/",
                "service": "Contrôle technique",
                "referralCode": referral_code,
            },
            "https://rdv.checkupauto.fr/",
        )

    def conversions(self):
        with analytics.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM booking_conversions ORDER BY external_id"
            ).fetchall()]

    def test_authoritative_conversion_replaces_browser_synthetic_row(self):
        intent = self.intent()
        booking.apply_conversion(
            {"externalId": "browser-placeholder", "status": "confirmed", "ccid": intent["token"]}
        )

        result = booking.apply_conversion(
            {
                "externalId": "mercure-9001",
                "status": "completed",
                "ccid": intent["token"],
                "amount": 80,
            }
        )

        self.assertEqual(result["syntheticConversionsReconciled"], 1)
        self.assertFalse(result["authoritativeConversionReused"])
        rows = self.conversions()
        self.assertEqual([row["external_id"] for row in rows], ["mercure-9001"])
        self.assertEqual(rows[0]["status"], "completed")
        self.assertEqual(booking.stats(30)["confirmedBookings"], 1)

    def test_late_browser_callback_reuses_authoritative_conversion(self):
        intent = self.intent()
        booking.apply_conversion(
            {
                "externalId": "mercure-9002",
                "status": "completed",
                "ccid": intent["token"],
                "amount": 80,
            }
        )

        result = booking.apply_conversion(
            {"externalId": "browser-late", "status": "confirmed", "ccid": intent["token"], "amount": 0}
        )

        self.assertTrue(result["authoritativeConversionReused"])
        self.assertEqual(result["externalId"], "mercure-9002")
        self.assertEqual(result["status"], "completed")
        rows = self.conversions()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["external_id"], "mercure-9002")
        self.assertEqual(rows[0]["amount_cents"], 8000)

    def test_reconciliation_is_scoped_to_same_attribution_key(self):
        first = self.intent()
        second = self.intent()
        booking.apply_conversion(
            {"externalId": "browser-first", "status": "confirmed", "ccid": first["token"]}
        )
        booking.apply_conversion(
            {"externalId": "mercure-second", "status": "confirmed", "ccid": second["token"]}
        )

        self.assertEqual(
            [row["external_id"] for row in self.conversions()],
            ["browser-first", "mercure-second"],
        )

    def test_referral_reward_moves_with_authoritative_conversion(self):
        account = referrals.create_account("PARRAIN-RECON")
        intent = self.intent(account["code"])
        booking.apply_conversion(
            {"externalId": "browser-referral", "status": "confirmed", "ccid": intent["token"]}
        )

        result = booking.apply_conversion(
            {"externalId": "mercure-referral", "status": "completed", "ccid": intent["token"]}
        )

        self.assertEqual(result["syntheticConversionsReconciled"], 1)
        self.assertEqual(result["referralStatus"], "earned")
        self.assertIsNone(referrals.reward_status(booking.PROVIDER, "browser-referral"))
        reward = referrals.reward_status(booking.PROVIDER, "mercure-referral")
        self.assertIsNotNone(reward)
        self.assertEqual(reward["status"], "earned")
        self.assertEqual(referrals.account_summary(account["code"])["balanceCents"], 500)


if __name__ == "__main__":
    unittest.main()
