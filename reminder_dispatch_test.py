import datetime
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import reminder_dispatch as dispatch


class ReminderDispatchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        dispatch.DATA_DIR = Path(self.tmp.name)
        dispatch.DB = dispatch.DATA_DIR / "reminder-dispatch.sqlite3"
        dispatch.init_db()

    def tearDown(self):
        self.tmp.cleanup()

    def add_target(self, due="2026-09-20"):
        dispatch._upsert([{
            "vehicleId": "vehicle-99", "clientKind": "account", "clientId": "12",
            "dueDate": due, "appointmentId": "77",
        }])

    @patch.object(dispatch.mercure, "session_status", return_value={"connected": True})
    @patch.object(dispatch.mercure, "reminder_source_rows")
    def test_sync_recent_and_one_backfill_chunk(self, source_rows, _session):
        source_rows.side_effect = [
            [{"vehicleId": "v1", "clientKind": "account", "clientId": "1", "dueDate": "2026-11-18", "appointmentId": "10"}],
            [{"vehicleId": "v2", "clientKind": "free", "clientId": "2", "dueDate": "2026-12-01", "appointmentId": "11"}],
        ]
        result = dispatch.sync_once(datetime.date(2026, 9, 19))
        self.assertTrue(result["ok"])
        self.assertEqual(result["recentRows"], 1)
        self.assertEqual(result["backfillRows"], 1)
        with dispatch.connect() as db:
            count = db.execute("SELECT COUNT(*) n FROM reminder_target").fetchone()["n"]
        self.assertEqual(count, 2)
        self.assertEqual(source_rows.call_count, 2)

    @patch.object(dispatch.mail, "configured", return_value=False)
    def test_waits_for_checkupauto_email_transport(self, _configured):
        self.add_target()
        now = datetime.datetime(2026, 9, 19, 12, 0, tzinfo=datetime.timezone.utc)
        result = dispatch.process_once(now, do_sync=False)
        self.assertEqual(result["state"], "waiting_email_transport")
        self.assertEqual(result["eligible"], 1)

    @patch.object(dispatch.notifications, "send_email")
    @patch.object(dispatch.mercure, "customer_email", return_value="client@example.fr")
    @patch.object(dispatch.mail, "configured", return_value=True)
    def test_sends_via_broker_without_persisting_email(self, _configured, _email, send_email):
        send_email.return_value = {"ok": True, "status": "sent"}
        self.add_target()
        now = datetime.datetime(2026, 9, 19, 12, 0, tzinfo=datetime.timezone.utc)
        result = dispatch.process_once(now, do_sync=False)
        self.assertEqual(result["sent"], 1)
        args, kwargs = send_email.call_args
        self.assertEqual(args[0], "client@example.fr")
        self.assertEqual(kwargs["category"], "ct_due_reminder")
        self.assertNotIn("vehicle-99", kwargs["reference"])
        with dispatch.connect() as db:
            columns = [row[1] for row in db.execute("PRAGMA table_info(reminder_target)")]
        self.assertNotIn("email", columns)

    def test_before_nine_does_not_dispatch(self):
        self.add_target()
        now = datetime.datetime(2026, 9, 19, 6, 0, tzinfo=datetime.timezone.utc)
        result = dispatch.process_once(now, do_sync=False)
        self.assertEqual(result["state"], "before_send_window")
        self.assertEqual(result["eligible"], 0)


if __name__ == "__main__":
    unittest.main()
