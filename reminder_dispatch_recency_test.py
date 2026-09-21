import datetime
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import reminder_dispatch as dispatch


class ReminderDispatchRecencyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_data_dir, self.old_db = dispatch.DATA_DIR, dispatch.DB
        dispatch.DATA_DIR = Path(self.tmp.name)
        dispatch.DB = dispatch.DATA_DIR / "reminder-dispatch.sqlite3"
        dispatch.init_db()

    def tearDown(self):
        dispatch.DATA_DIR, dispatch.DB = self.old_data_dir, self.old_db
        self.tmp.cleanup()

    @staticmethod
    def row(client_id, appointment_id="77"):
        return {
            "vehicleId": "vehicle-99",
            "clientKind": "account",
            "clientId": client_id,
            "dueDate": "2026-11-18",
            "appointmentId": appointment_id,
        }

    def target(self):
        with dispatch.connect() as db:
            row = db.execute(
                "SELECT client_id,source_window_end,quarantined FROM reminder_target WHERE vehicle_id=?",
                ("vehicle-99",),
            ).fetchone()
        return dict(row) if row else None

    def test_older_backfill_cannot_replace_newer_recipient_identity(self):
        dispatch._upsert([self.row("current")], "2026-09-20")
        dispatch._upsert([self.row("historical", "11")], "2026-08-01")
        target = self.target()
        self.assertEqual(target["client_id"], "current")
        self.assertEqual(target["source_window_end"], "2026-09-20")
        self.assertEqual(target["quarantined"], 0)

    def test_ambiguous_current_window_is_quarantined_from_all_delivery_sources(self):
        applied = dispatch._upsert(
            [self.row("client-a", "10"), self.row("client-b", "11")],
            "2026-09-20",
        )
        self.assertEqual(applied, 1)
        self.assertEqual(self.target()["quarantined"], 1)
        now = datetime.datetime(2026, 9, 19, 12, 0, tzinfo=datetime.timezone.utc)
        self.assertEqual(dispatch._eligible(now), [])
        self.assertEqual(dispatch.deadlines_for_vehicle_ids(["vehicle-99"]), [])
        self.assertEqual(dispatch.mobile_claim_candidates(), [])
        with self.assertRaises(LookupError):
            dispatch.mobile_claim_target("vehicle-99")

    def test_older_ambiguous_backfill_cannot_quarantine_newer_verified_target(self):
        dispatch._upsert([self.row("current")], "2026-09-20")
        dispatch._upsert(
            [self.row("old-a", "10"), self.row("old-b", "11")],
            "2026-08-01",
        )
        target = self.target()
        self.assertEqual(target["client_id"], "current")
        self.assertEqual(target["quarantined"], 0)

    @patch.object(dispatch.mercure, "session_status", return_value={"connected": True})
    @patch.object(dispatch.mercure, "reminder_source_rows")
    def test_sync_recent_identity_wins_over_backfill_processed_after_it(self, source_rows, _session):
        source_rows.side_effect = [
            [self.row("current", "200")],
            [self.row("historical", "100")],
        ]
        result = dispatch.sync_once(datetime.date(2026, 9, 19))
        self.assertTrue(result["ok"])
        self.assertEqual(result["quarantinedTargets"], 0)
        target = self.target()
        self.assertEqual(target["client_id"], "current")
        self.assertEqual(target["source_window_end"], "2026-09-20")

    def test_newer_unambiguous_window_releases_quarantine(self):
        dispatch._upsert(
            [self.row("client-a", "10"), self.row("client-b", "11")],
            "2026-09-20",
        )
        dispatch._upsert([self.row("client-b", "12")], "2026-09-21")
        target = self.target()
        self.assertEqual(target["client_id"], "client-b")
        self.assertEqual(target["source_window_end"], "2026-09-21")
        self.assertEqual(target["quarantined"], 0)


if __name__ == "__main__":
    unittest.main()
