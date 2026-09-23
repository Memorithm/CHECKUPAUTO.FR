import datetime
import tempfile
import unittest
from pathlib import Path

import analytics_store as analytics
import booking_bridge as booking


class BookingTokenRetirementTest(unittest.TestCase):
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

    def _intent(self):
        return booking.create_intent(
            {
                "referrer": "https://www.google.com/search?q=controle-technique",
                "utmSource": "google",
                "utmCampaign": "automne-2026",
                "device": "mobile",
                "path": "/services/controle-technique",
                "service": "controle technique",
                "referralCode": "",
            },
            "https://rdv.checkupauto.fr/",
        )

    def test_retirement_replaces_raw_token_but_keeps_late_provider_attribution(self):
        intent = self._intent()
        raw = intent["token"]
        browser_proof = booking.browser_token(raw)
        now = datetime.datetime(2026, 9, 23, 20, 0, tzinfo=datetime.timezone.utc)
        created = (now - datetime.timedelta(hours=49)).isoformat(timespec="seconds")
        with analytics.connect() as db:
            db.execute("UPDATE booking_intents SET created_at=? WHERE token=?", (created, raw))
            key = str(db.execute(
                "SELECT attribution_key FROM booking_intents WHERE token=?", (raw,)
            ).fetchone()["attribution_key"])

        self.assertEqual(booking.retire_expired_browser_tokens(now=now, dry_run=True), 1)
        with analytics.connect() as db:
            self.assertIsNotNone(db.execute(
                "SELECT 1 FROM booking_intents WHERE token=?", (raw,)
            ).fetchone())

        self.assertEqual(booking.retire_expired_browser_tokens(now=now), 1)
        self.assertEqual(booking.retire_expired_browser_tokens(now=now), 0)
        with analytics.connect() as db:
            row = db.execute(
                "SELECT token,attribution_key,source,campaign FROM booking_intents"
            ).fetchone()
        self.assertEqual(str(row["token"]), key)
        self.assertEqual(str(row["attribution_key"]), key)
        self.assertTrue(key.startswith("sha256-v1:"))
        self.assertNotEqual(key, raw)
        self.assertEqual(str(row["source"]), "Google")
        self.assertEqual(str(row["campaign"]), "automne-2026")

        # Re-running schema migration must not hash an already-retired key again.
        booking.init_db()
        with analytics.connect() as db:
            migrated = db.execute(
                "SELECT token,attribution_key FROM booking_intents"
            ).fetchone()
        self.assertEqual(str(migrated["token"]), key)
        self.assertEqual(str(migrated["attribution_key"]), key)

        # Mercure may still return the original ccid after the browser lifetime.
        # The derived key keeps source attribution without retaining that ccid.
        result = booking.apply_conversion({
            "externalId": "mercure-late-1",
            "status": "cancelled",
            "attributionToken": raw,
        })
        self.assertTrue(result["attributed"])
        self.assertEqual(result["source"], "Google")
        with analytics.connect() as db:
            persisted = db.execute(
                "SELECT attribution_token,source FROM booking_conversions WHERE external_id=?",
                ("mercure-late-1",),
            ).fetchone()
        self.assertEqual(str(persisted["attribution_token"]), key)
        self.assertEqual(str(persisted["source"]), "Google")

        # The expired browser credential itself can no longer resolve an intent.
        with self.assertRaisesRegex(ValueError, "unknown attribution token"):
            booking.browser_confirmation({"ccid": raw, "cct": browser_proof, "route": "/confirmation"})

    def test_unexpired_token_is_not_retired(self):
        intent = self._intent()
        raw = intent["token"]
        now = datetime.datetime(2026, 9, 23, 20, 0, tzinfo=datetime.timezone.utc)
        created = (now - datetime.timedelta(hours=47, minutes=59)).isoformat(timespec="seconds")
        with analytics.connect() as db:
            db.execute("UPDATE booking_intents SET created_at=? WHERE token=?", (created, raw))

        self.assertEqual(booking.retire_expired_browser_tokens(now=now), 0)
        with analytics.connect() as db:
            row = db.execute("SELECT token FROM booking_intents").fetchone()
        self.assertEqual(str(row["token"]), raw)

    def test_naive_retirement_clock_is_rejected(self):
        self._intent()
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            booking.retire_expired_browser_tokens(now=datetime.datetime(2026, 9, 23, 20, 0))


if __name__ == "__main__":
    unittest.main()
