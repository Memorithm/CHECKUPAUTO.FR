import tempfile
import unittest
from pathlib import Path

import analytics_store as analytics
import booking_bridge as booking
import booking_conversion_reconciliation as reconciliation


class BookingConversionReconciliationRunnerTest(unittest.TestCase):
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

    def seed(self, external_id, attribution_key, status="confirmed", amount_cents=0):
        now = "2026-09-24T06:00:00+00:00"
        with analytics.connect() as db:
            db.execute(
                """INSERT INTO booking_conversions(
                     provider,external_id,status,first_seen_at,updated_at,confirmed_at,
                     appointment_at,amount_cents,service,attribution_token,source,campaign,device,referral_code
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    booking.PROVIDER, external_id, status, now, now,
                    now if status in booking.CONFIRMED else None, "", amount_cents,
                    "Contrôle technique", attribution_key, "Google", "", "mobile", "",
                ),
            )

    def ids(self):
        with analytics.connect() as db:
            return [str(row["external_id"]) for row in db.execute(
                "SELECT external_id FROM booking_conversions ORDER BY external_id"
            ).fetchall()]

    def test_removes_only_synthetic_row_with_same_derived_attribution(self):
        key = booking._attribution_key("legacy-token")
        other = booking._attribution_key("other-token")
        self.seed("browser-legacy", key)
        self.seed("mercure-42", key, status="completed", amount_cents=8000)
        self.seed("browser-other", other)

        result = reconciliation.process_once()

        self.assertEqual(result["reconciledRows"], 1)
        self.assertEqual(result["unresolvedSyntheticRows"], 1)
        self.assertFalse(result["providerIdInferenceUsed"])
        self.assertEqual(self.ids(), ["browser-other", "mercure-42"])
        self.assertEqual(booking.stats(30)["confirmedBookings"], 2)

    def test_authoritative_cancelled_row_still_supersedes_browser_confirmation(self):
        key = booking._attribution_key("cancelled-token")
        self.seed("browser-old", key, status="confirmed")
        self.seed("mercure-cancelled", key, status="cancelled")

        result = reconciliation.process_once()

        self.assertEqual(result["reconciledRows"], 1)
        self.assertEqual(self.ids(), ["mercure-cancelled"])

    def test_browser_only_rows_are_retained_without_inference(self):
        key = booking._attribution_key("browser-only-token")
        self.seed("browser-only", key)
        self.seed("browser-no-key", "")

        first = reconciliation.process_once()
        second = reconciliation.process_once()

        self.assertEqual(first["reconciledRows"], 0)
        self.assertEqual(first["unresolvedSyntheticRows"], 1)
        self.assertEqual(first["syntheticRowsWithoutAttribution"], 1)
        self.assertEqual(second, first)
        self.assertEqual(self.ids(), ["browser-no-key", "browser-only"])

    def test_non_browser_rows_are_never_deleted(self):
        key = booking._attribution_key("multi-provider-token")
        self.seed("mercure-a", key, status="confirmed")
        self.seed("mercure-b", key, status="completed")

        result = reconciliation.process_once()

        self.assertEqual(result["reconciledRows"], 0)
        self.assertEqual(self.ids(), ["mercure-a", "mercure-b"])


if __name__ == "__main__":
    unittest.main()
