import json
import re
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

    def test_verified_mercure_appointment_formats_are_preserved(self):
        fixtures = {
            "mercure-appointment-iso": "2026-09-19T10:00",
            "mercure-appointment-sql": "2026-09-19 10:00:00",
        }
        for external_id, appointment_at in fixtures.items():
            booking.apply_conversion({
                "externalId": external_id,
                "status": "confirmed",
                "appointmentDate": appointment_at,
                "amount": 80,
            })

        with analytics.connect() as db:
            rows = {
                row["external_id"]: row["appointment_at"]
                for row in db.execute(
                    "SELECT external_id,appointment_at FROM booking_conversions WHERE external_id LIKE 'mercure-appointment-%'"
                )
            }

        self.assertEqual(rows, fixtures)

    def test_unstructured_appointment_date_is_rejected_without_persistence(self):
        email = "client@example.com"
        with self.assertRaisesRegex(ValueError, "appointmentDate invalid"):
            booking.apply_conversion({
                "externalId": "mercure-appointment-pii",
                "status": "confirmed",
                "appointmentDate": email,
                "amount": 80,
            })

        with analytics.connect() as db:
            count = db.execute(
                "SELECT COUNT(*) FROM booking_conversions WHERE external_id=?",
                ("mercure-appointment-pii",),
            ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_invalid_calendar_appointment_date_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "appointmentDate invalid"):
            booking.apply_conversion({
                "externalId": "mercure-appointment-invalid-calendar",
                "status": "confirmed",
                "appointmentDate": "2026-02-31T10:00",
                "amount": 80,
            })

    def test_conversion_persists_only_derived_attribution_key(self):
        intent = booking.create_intent({
            "utmSource": "google",
            "device": "desktop",
            "path": "/reservation",
            "service": "Contrôle technique",
        }, "https://rdv.checkupauto.fr/")
        raw_token = intent["token"]

        booking.apply_conversion({
            "externalId": "mercure-attribution-key-1",
            "status": "confirmed",
            "ccid": raw_token,
            "amount": 80,
        })

        with analytics.connect() as db:
            conversion = db.execute(
                "SELECT attribution_token FROM booking_conversions WHERE external_id=?",
                ("mercure-attribution-key-1",),
            ).fetchone()["attribution_token"]
            intent_row = db.execute(
                "SELECT token,attribution_key FROM booking_intents WHERE token=?",
                (raw_token,),
            ).fetchone()

        self.assertEqual(intent_row["token"], raw_token)
        self.assertNotEqual(conversion, raw_token)
        self.assertEqual(conversion, intent_row["attribution_key"])
        self.assertRegex(conversion, r"^sha256-v1:[0-9a-f]{64}$")
        self.assertEqual(booking.stats(30)["pendingIntents"], 0)

    def test_legacy_raw_conversion_token_is_migrated_without_breaking_stats(self):
        intent = booking.create_intent({
            "utmSource": "direct",
            "device": "mobile",
            "path": "/reservation",
        }, "https://rdv.checkupauto.fr/")
        raw_token = intent["token"]
        now = booking.now_iso()
        with analytics.connect() as db:
            db.execute(
                """INSERT INTO booking_conversions(
                   provider,external_id,status,first_seen_at,updated_at,confirmed_at,
                   attribution_token,source,device
                   ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    booking.PROVIDER,
                    "legacy-conversion-token",
                    "confirmed",
                    now,
                    now,
                    now,
                    raw_token,
                    "Direct",
                    "mobile",
                ),
            )
            db.execute(
                "DELETE FROM booking_schema_meta WHERE key=?",
                (booking._BOOKING_ATTRIBUTION_STORAGE_KEY,),
            )

        booking.init_db()
        with analytics.connect() as db:
            stored = db.execute(
                "SELECT attribution_token FROM booking_conversions WHERE external_id=?",
                ("legacy-conversion-token",),
            ).fetchone()["attribution_token"]
            key = db.execute(
                "SELECT attribution_key FROM booking_intents WHERE token=?",
                (raw_token,),
            ).fetchone()["attribution_key"]
            marker = db.execute(
                "SELECT value FROM booking_schema_meta WHERE key=?",
                (booking._BOOKING_ATTRIBUTION_STORAGE_KEY,),
            ).fetchone()["value"]

        self.assertEqual(stored, key)
        self.assertNotEqual(stored, raw_token)
        self.assertEqual(marker, "sha256-v1")
        self.assertEqual(booking.stats(30)["pendingIntents"], 0)

    def test_init_repairs_raw_conversion_written_by_older_process(self):
        intent = booking.create_intent({
            "device": "desktop",
            "path": "/reservation",
        }, "https://rdv.checkupauto.fr/")
        raw_token = intent["token"]
        now = booking.now_iso()
        with analytics.connect() as db:
            db.execute(
                """INSERT INTO booking_conversions(
                   provider,external_id,status,first_seen_at,updated_at,confirmed_at,
                   attribution_token
                   ) VALUES(?,?,?,?,?,?,?)""",
                (
                    booking.PROVIDER,
                    "rolling-conversion-token",
                    "confirmed",
                    now,
                    now,
                    now,
                    raw_token,
                ),
            )

        booking.init_db()
        with analytics.connect() as db:
            first = db.execute(
                "SELECT attribution_token FROM booking_conversions WHERE external_id=?",
                ("rolling-conversion-token",),
            ).fetchone()["attribution_token"]
        booking.init_db()
        with analytics.connect() as db:
            second = db.execute(
                "SELECT attribution_token FROM booking_conversions WHERE external_id=?",
                ("rolling-conversion-token",),
            ).fetchone()["attribution_token"]

        self.assertEqual(first, second)
        self.assertRegex(second, r"^sha256-v1:[0-9a-f]{64}$")
        self.assertNotEqual(second, raw_token)


if __name__ == "__main__":
    unittest.main()
