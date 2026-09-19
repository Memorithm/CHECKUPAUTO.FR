import tempfile
import unittest
from pathlib import Path

import analytics_store as analytics
import booking_bridge as booking
import referral_engine as referrals


class ReferralBookingIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.old_db = analytics.DB
        self.old_secret = booking.SECRET_FILE
        analytics.DB = root / "analytics.sqlite3"
        booking.SECRET_FILE = root / "mercure-webhook-secret"
        analytics.init_db()
        booking.init_db()
        self.account = referrals.create_account("PARRAIN-01")

    def tearDown(self):
        analytics.DB = self.old_db
        booking.SECRET_FILE = self.old_secret
        self.tmp.cleanup()

    def intent(self):
        return booking.create_intent(
            {
                "referrer": "",
                "utmSource": "",
                "utmCampaign": "",
                "device": "mobile",
                "path": "/",
                "service": "Contrôle technique",
                "referralCode": self.account["code"],
            },
            "https://rdv.checkupauto.fr/",
        )

    def test_confirmed_booking_is_pending_completed_control_earns(self):
        intent = self.intent()
        confirmed = booking.apply_conversion(
            {
                "externalId": "rdv-100",
                "status": "confirmed",
                "ccid": intent["token"],
                "service": "Contrôle technique",
                "amount": 80,
            }
        )
        self.assertEqual(confirmed["referralStatus"], "pending")
        summary = referrals.account_summary(self.account["code"])
        self.assertEqual(summary["balanceCents"], 0)
        self.assertEqual(summary["pendingCents"], 500)

        completed = booking.apply_conversion(
            {
                "externalId": "rdv-100",
                "status": "completed",
                "ccid": intent["token"],
                "service": "Contrôle technique",
                "amount": 80,
            }
        )
        self.assertEqual(completed["referralStatus"], "earned")
        summary = referrals.account_summary(self.account["code"])
        self.assertEqual(summary["balanceCents"], 500)
        self.assertEqual(summary["pendingCents"], 0)

    def test_browser_placeholder_migrates_to_real_mercure_id(self):
        intent = self.intent()
        booking.apply_conversion(
            {
                "externalId": "browser-placeholder",
                "status": "confirmed",
                "ccid": intent["token"],
            }
        )
        result = booking.apply_conversion(
            {
                "externalId": "mercure-9001",
                "status": "completed",
                "ccid": intent["token"],
            }
        )
        self.assertEqual(result["referralStatus"], "earned")
        reward = referrals.reward_status("mercure-rdv", "mercure-9001")
        self.assertIsNotNone(reward)
        self.assertEqual(referrals.account_summary(self.account["code"])["balanceCents"], 500)

    def test_no_show_cancels_pending_reward(self):
        intent = self.intent()
        booking.apply_conversion(
            {
                "externalId": "rdv-no-show",
                "status": "confirmed",
                "ccid": intent["token"],
            }
        )
        result = booking.apply_conversion(
            {
                "externalId": "rdv-no-show",
                "status": "no_show",
                "ccid": intent["token"],
            }
        )
        self.assertEqual(result["referralStatus"], "cancelled")
        self.assertEqual(referrals.account_summary(self.account["code"])["balanceCents"], 0)


if __name__ == "__main__":
    unittest.main()
