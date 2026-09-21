import datetime
import sqlite3
import tempfile
import unittest
from pathlib import Path

import gmail_operational_evidence as evidence


class GmailOperationalEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "notification-broker.sqlite3"

    def tearDown(self):
        self.tmp.cleanup()

    def _row(self, *, success="", failure="", failures=0, open_until=""):
        with sqlite3.connect(self.db) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS notification_transport_health(
                transport_key TEXT PRIMARY KEY,
                consecutive_failures INTEGER NOT NULL DEFAULT 0,
                open_until TEXT NOT NULL DEFAULT '',
                last_failure_at TEXT NOT NULL DEFAULT '',
                last_success_at TEXT NOT NULL DEFAULT ''
            )""")
            db.execute(
                """INSERT OR REPLACE INTO notification_transport_health(
                    transport_key, consecutive_failures, open_until,
                    last_failure_at, last_success_at
                ) VALUES(?,?,?,?,?)""",
                (evidence.TRANSPORT_KEY, failures, open_until, failure, success),
            )

    def test_missing_store_is_unverified_without_creating_it(self):
        result = evidence.status(self.db)
        self.assertEqual(result["verification"], "unverified")
        self.assertFalse(self.db.exists())

    def test_real_success_is_verified(self):
        self._row(success="2026-09-21T15:00:00+00:00")
        result = evidence.status(self.db)
        self.assertEqual(result["verification"], "verified")
        self.assertTrue(result["operationallyVerified"])

    def test_newer_failure_invalidates_success(self):
        self._row(
            success="2026-09-21T15:00:00+00:00",
            failure="2026-09-21T16:00:00+00:00",
            failures=1,
        )
        result = evidence.status(self.db)
        self.assertEqual(result["verification"], "unavailable")
        self.assertFalse(result["operationallyVerified"])

    def test_open_circuit_is_unavailable(self):
        future = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=10)).isoformat()
        self._row(success="2026-09-21T15:00:00+00:00", open_until=future)
        result = evidence.status(self.db)
        self.assertEqual(result["verification"], "unavailable")
        self.assertTrue(result["circuitOpen"])

    def test_corrupt_timestamp_fails_closed_without_error_detail(self):
        self._row(success="not-a-timestamp")
        result = evidence.status(self.db)
        self.assertEqual(result["verification"], "unavailable")
        self.assertNotIn("error", result)

    def test_corrupt_failure_counter_fails_closed_without_error_detail(self):
        self._row(success="2026-09-21T15:00:00+00:00", failures="invalid")
        result = evidence.status(self.db)
        self.assertEqual(result["verification"], "unavailable")
        self.assertFalse(result["operationallyVerified"])
        self.assertNotIn("error", result)


if __name__ == "__main__":
    unittest.main()
