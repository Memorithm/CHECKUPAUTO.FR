import json
import tempfile
import unittest
from pathlib import Path

import analytics_store as analytics
import booking_bridge as booking


class BookingConversionPrivacyTest(unittest.TestCase):
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

    def test_provider_dimensions_are_redacted_before_conversion_insert(self):
        email = "client@example.com"
        phone = "0612345678"
        result = booking.apply_conversion({
            "externalId": "mercure-privacy-1",
            "status": "confirmed",
            "service": f"Contrôle technique {email}",
            "source": phone,
            "amount": 80,
        })

        with analytics.connect() as db:
            row = dict(db.execute(
                "SELECT service,source FROM booking_conversions WHERE provider=? AND external_id=?",
                (booking.PROVIDER, "mercure-privacy-1"),
            ).fetchone())

        self.assertEqual(row["service"], "[redacted]")
        self.assertEqual(row["source"], "[redacted]")
        serialized = json.dumps({"row": row, "result": result}, ensure_ascii=False, sort_keys=True)
        self.assertNotIn(email, serialized)
        self.assertNotIn(phone, serialized)

    def test_normal_provider_dimensions_remain_usable(self):
        result = booking.apply_conversion({
            "externalId": "mercure-privacy-2",
            "status": "confirmed",
            "service": "Contrôle technique",
            "source": "Google Ads",
            "amount": 80,
        })

        with analytics.connect() as db:
            row = dict(db.execute(
                "SELECT service,source FROM booking_conversions WHERE provider=? AND external_id=?",
                (booking.PROVIDER, "mercure-privacy-2"),
            ).fetchone())

        self.assertEqual(row["service"], "Contrôle technique")
        self.assertEqual(row["source"], "Google Ads")
        self.assertEqual(result["source"], "Google Ads")
        self.assertTrue(result["attributed"])

    def test_sanitized_intent_dimensions_are_not_overridden_by_callback_source(self):
        intent = booking.create_intent({
            "referrer": "https://www.google.com/search?q=controle",
            "utmSource": "google",
            "utmCampaign": "automne-2026",
            "device": "desktop",
            "path": "/services/controle-technique",
            "service": "Contrôle technique",
            "referralCode": "",
        }, "https://rdv.checkupauto.fr/")

        booking.apply_conversion({
            "externalId": "mercure-privacy-3",
            "status": "confirmed",
            "ccid": intent["token"],
            "source": "client@example.com",
            "amount": 80,
        })

        with analytics.connect() as db:
            row = dict(db.execute(
                "SELECT service,source,campaign,device FROM booking_conversions WHERE provider=? AND external_id=?",
                (booking.PROVIDER, "mercure-privacy-3"),
            ).fetchone())

        self.assertEqual(row, {
            "service": "Contrôle technique",
            "source": "Google",
            "campaign": "automne-2026",
            "device": "desktop",
        })


if __name__ == "__main__":
    unittest.main()
