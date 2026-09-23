import json
import tempfile
import unittest
from pathlib import Path

import analytics_store as analytics
import booking_bridge as booking


class BookingIntentPrivacyTest(unittest.TestCase):
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

    def _create(self, **overrides):
        payload = {
            "referrer": "",
            "utmSource": "",
            "utmCampaign": "automne-2026",
            "device": "mobile",
            "path": "/services/controle-technique",
            "service": "controle technique",
            "referralCode": "",
        }
        payload.update(overrides)
        return booking.create_intent(payload, "https://rdv.checkupauto.fr/")

    def test_subject_specific_public_dimensions_are_redacted_before_both_inserts(self):
        email = "client@example.com"
        phone = "0612345678"
        result = self._create(
            referrer=f"https://tracker.example/{email}?phone={phone}",
            utmSource=email,
            utmCampaign=email,
            path=f"/clients/{email}?phone={phone}",
            service=phone,
        )

        with analytics.connect() as db:
            intent = dict(db.execute(
                "SELECT source,campaign,path,service FROM booking_intents WHERE token=?",
                (result["token"],),
            ).fetchone())
            event = dict(db.execute(
                "SELECT source,campaign,path,service FROM events WHERE event='booking_click' ORDER BY id DESC LIMIT 1"
            ).fetchone())

        self.assertEqual(intent["source"], "UTM")
        self.assertEqual(intent["campaign"], "[redacted]")
        self.assertEqual(intent["path"], "/redacted")
        self.assertEqual(intent["service"], "[redacted]")
        self.assertEqual(event, intent)
        serialized = json.dumps({"intent": intent, "event": event, "result": result}, sort_keys=True)
        self.assertNotIn(email, serialized)
        self.assertNotIn(phone, serialized)

    def test_query_string_is_dropped_without_losing_normal_attribution(self):
        result = self._create(
            referrer="https://www.google.com/search?q=controle",
            utmSource="google",
            path="/services/controle-technique?email=client@example.com",
        )
        with analytics.connect() as db:
            row = db.execute(
                "SELECT source,campaign,path,service FROM booking_intents WHERE token=?",
                (result["token"],),
            ).fetchone()
        self.assertEqual(str(row["source"]), "Google")
        self.assertEqual(str(row["campaign"]), "automne-2026")
        self.assertEqual(str(row["path"]), "/services/controle-technique")
        self.assertEqual(str(row["service"]), "controle technique")


if __name__ == "__main__":
    unittest.main()
