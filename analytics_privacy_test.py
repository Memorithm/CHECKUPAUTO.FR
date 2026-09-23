import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import analytics_store as analytics


class AnalyticsPrivacyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "analytics.sqlite3"
        self.patch = patch.object(analytics, "DB", self.db)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        analytics.init_db()

    def _latest(self):
        with analytics.connect() as db:
            return db.execute("SELECT * FROM events ORDER BY id DESC LIMIT 1").fetchone()

    def test_query_string_and_unknown_referrer_host_are_not_persisted(self):
        analytics.record_event(
            {
                "event": "page_view",
                "path": "/app?email=alice@example.test&token=secret",
                "device": "mobile",
                "referrer": "https://alice.customer.example/private/path",
            }
        )

        row = self._latest()
        self.assertEqual(row["path"], "/app")
        self.assertEqual(row["source"], "Referral")
        self.assertEqual(row["referrer_host"], "other")
        raw = self.db.read_bytes()
        self.assertNotIn(b"alice@example.test", raw)
        self.assertNotIn(b"alice.customer.example", raw)
        self.assertNotIn(b"token=secret", raw)

    def test_obvious_subject_identifiers_are_redacted_from_dimensions(self):
        analytics.record_event(
            {
                "event": "service_selected",
                "path": "/vehicle/4a8c91bf-58e0-4bd3-8b43-7fd77303d20f",
                "device": "desktop",
                "utmSource": "alice@example.test",
                "utmCampaign": "+33612345678",
                "service": "owner@example.test",
            }
        )

        row = self._latest()
        self.assertEqual(row["path"], "/redacted")
        self.assertEqual(row["source"], "UTM")
        self.assertEqual(row["campaign"], "[redacted]")
        self.assertEqual(row["service"], "[redacted]")
        raw = self.db.read_bytes()
        self.assertNotIn(b"4a8c91bf-58e0-4bd3-8b43-7fd77303d20f", raw)
        self.assertNotIn(b"alice@example.test", raw)
        self.assertNotIn(b"+33612345678", raw)
        self.assertNotIn(b"owner@example.test", raw)

    def test_known_acquisition_dimensions_remain_usable(self):
        analytics.record_event(
            {
                "event": "app_landing_view",
                "path": "/app",
                "device": "mobile",
                "referrer": "https://www.google.fr/search?q=controle-technique",
                "utmSource": "google",
                "utmCampaign": "ios-reminder-app",
                "service": "testflight",
            }
        )

        row = self._latest()
        self.assertEqual(row["path"], "/app")
        self.assertEqual(row["source"], "Google")
        self.assertEqual(row["referrer_host"], "google")
        self.assertEqual(row["campaign"], "ios-reminder-app")
        self.assertEqual(row["service"], "testflight")

    def test_privacy_profile_matches_persisted_schema_boundary(self):
        profile = analytics.privacy_profile(180)
        self.assertFalse(profile["subjectKeyed"])
        self.assertFalse(profile["clientIpStored"])
        self.assertFalse(profile["cookieOrSessionStored"])
        self.assertFalse(profile["queryStringStored"])
        self.assertFalse(profile["unknownReferrerHostStored"])
        self.assertTrue(profile["obviousSubjectIdentifiersRedacted"])
        self.assertEqual(profile["retentionDays"], 180)
        self.assertIn("retention_enforcement", profile["retentionEnforcedBy"])


if __name__ == "__main__":
    unittest.main()
