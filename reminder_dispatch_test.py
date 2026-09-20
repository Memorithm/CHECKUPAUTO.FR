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
    @patch.object(dispatch.mail, "preflight", return_value={"ok": True, "state": "ready"})
    @patch.object(dispatch.mail, "configured", return_value=True)
    def test_sends_via_broker_without_persisting_email(self, _configured, _preflight, _email, send_email):
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


    @patch.object(dispatch.notifications, "send_email")
    @patch.object(dispatch.mercure, "customer_email", return_value="client@example.fr")
    @patch.object(dispatch.mail, "preflight", return_value={"ok": False, "state": "awaiting_credentials"})
    @patch.object(dispatch.mail, "configured", return_value=True)
    def test_preflight_blocks_recipient_lookup_and_broker_delivery(self, _configured, _preflight, customer_email, send_email):
        self.add_target()
        now = datetime.datetime(2026, 9, 19, 12, 0, tzinfo=datetime.timezone.utc)
        result = dispatch.process_once(now, do_sync=False)
        self.assertTrue(result["ok"])
        self.assertEqual(result["state"], "waiting_email_preflight")
        self.assertEqual(result["preflightState"], "awaiting_credentials")
        self.assertEqual(result["eligible"], 1)
        customer_email.assert_not_called()
        send_email.assert_not_called()

    @patch.object(dispatch.notifications, "send_email")
    @patch.object(dispatch.mercure, "customer_email", return_value="client@example.fr")
    @patch.object(dispatch.mail, "preflight", side_effect=RuntimeError("provider details must not escape"))
    @patch.object(dispatch.mail, "configured", return_value=True)
    def test_preflight_exception_is_safe_and_does_not_resolve_recipient(self, _configured, _preflight, customer_email, send_email):
        self.add_target()
        now = datetime.datetime(2026, 9, 19, 12, 0, tzinfo=datetime.timezone.utc)
        result = dispatch.process_once(now, do_sync=False)
        self.assertFalse(result["ok"])
        self.assertEqual(result["state"], "email_preflight_failed")
        self.assertEqual(result["preflightState"], "unavailable")
        self.assertNotIn("provider", str(result))
        customer_email.assert_not_called()
        send_email.assert_not_called()

    @patch.object(dispatch.notifications, "send_email", side_effect=dispatch.notifications.PermanentDeliverySuppressed("suppressed"))
    @patch.object(dispatch.mercure, "customer_email", return_value="client@example.fr")
    @patch.object(dispatch.mail, "preflight", return_value={"ok": True, "state": "ready"})
    @patch.object(dispatch.mail, "configured", return_value=True)
    def test_existing_permanent_failure_is_observed_without_counting_new_delivery_failure(self, _configured, _preflight, _email, send_email):
        self.add_target()
        now = datetime.datetime(2026, 9, 19, 12, 0, tzinfo=datetime.timezone.utc)
        result = dispatch.process_once(now, do_sync=False)
        self.assertTrue(result["ok"])
        self.assertEqual(result["state"], "active_with_permanent_suppressions")
        self.assertEqual(result["permanentSuppressed"], 1)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(send_email.call_count, 1)

    def test_before_nine_does_not_dispatch(self):
        self.add_target()
        now = datetime.datetime(2026, 9, 19, 6, 0, tzinfo=datetime.timezone.utc)
        result = dispatch.process_once(now, do_sync=False)
        self.assertEqual(result["state"], "before_send_window")
        self.assertEqual(result["eligible"], 0)


    @patch.object(dispatch.notifications, "permanent_failure_recipient_state", return_value={
        "ok": True, "incidentId": "a" * 32, "recipientState": "changed", "permanentState": "open",
    })
    @patch.object(dispatch.notifications, "permanent_failure_context")
    @patch.object(dispatch.mercure, "customer_email", return_value="corrected@example.fr")
    def test_permanent_recipient_check_reports_change_without_pii(self, customer_email, context, compare):
        self.add_target(due="2026-09-20")
        reference = dispatch._reference({
            "vehicle_id": "vehicle-99", "due_date": "2026-09-20", "days_before": 1,
        })
        context.return_value = {
            "incidentId": "a" * 32, "channel": "email", "category": "ct_due_reminder",
            "reference": reference, "permanentState": "open",
        }
        result = dispatch.permanent_recipient_check("a" * 32)
        self.assertTrue(result["ok"])
        self.assertEqual(result["recipientState"], "changed")
        self.assertTrue(result["retryEligible"])
        self.assertNotIn("corrected@example.fr", str(result))
        self.assertNotIn("hash", str(result).lower())
        customer_email.assert_called_once_with("account", "12")
        compare.assert_called_once_with("a" * 32, "corrected@example.fr")

    @patch.object(dispatch.notifications, "send_email", return_value={"ok": True, "status": "sent"})
    @patch.object(dispatch.notifications, "permanent_failure_recipient_state", return_value={
        "ok": True, "incidentId": "b" * 32, "recipientState": "changed", "permanentState": "open",
    })
    @patch.object(dispatch.notifications, "permanent_failure_context")
    @patch.object(dispatch.mercure, "customer_email", return_value="corrected@example.fr")
    @patch.object(dispatch.mail, "preflight", return_value={"ok": True, "state": "ready"})
    def test_permanent_recipient_retry_requires_changed_recipient_and_green_preflight(
        self, preflight, customer_email, context, compare, send_email
    ):
        self.add_target(due="2026-09-20")
        reference = dispatch._reference({
            "vehicle_id": "vehicle-99", "due_date": "2026-09-20", "days_before": 1,
        })
        context.return_value = {
            "incidentId": "b" * 32, "channel": "email", "category": "ct_due_reminder",
            "reference": reference, "permanentState": "open",
        }
        result = dispatch.permanent_recipient_retry("b" * 32)
        self.assertTrue(result["ok"])
        self.assertEqual(result["state"], "resent")
        self.assertNotIn("corrected@example.fr", str(result))
        send_email.assert_called_once()
        args, kwargs = send_email.call_args
        self.assertEqual(args[0], "corrected@example.fr")
        self.assertEqual(kwargs["reference"], reference)
        self.assertEqual(kwargs["category"], "ct_due_reminder")

    @patch.object(dispatch.notifications, "record_permanent_recipient_check", return_value={
        "ok": True, "incidentId": "d" * 32, "recipientState": "missing", "recipientCheckedAt": "2026-09-20T12:00:00+00:00",
    })
    @patch.object(dispatch.notifications, "permanent_failure_context")
    @patch.object(dispatch.mercure, "customer_email", return_value="")
    def test_permanent_recipient_check_persists_missing_state_without_pii(self, customer_email, context, record):
        self.add_target(due="2026-09-20")
        reference = dispatch._reference({
            "vehicle_id": "vehicle-99", "due_date": "2026-09-20", "days_before": 1,
        })
        context.return_value = {
            "incidentId": "d" * 32, "channel": "email", "category": "ct_due_reminder",
            "reference": reference, "permanentState": "open",
        }
        result = dispatch.permanent_recipient_check("d" * 32)
        self.assertTrue(result["ok"])
        self.assertEqual(result["recipientState"], "missing")
        self.assertFalse(result["retryEligible"])
        record.assert_called_once_with("d" * 32, "missing")
        self.assertNotIn("@", str(result))

    @patch.object(dispatch.notifications, "record_permanent_recipient_check", return_value={
        "ok": True, "incidentId": "e" * 32, "recipientState": "lookup_failed", "recipientCheckedAt": "2026-09-20T12:00:00+00:00",
    })
    @patch.object(dispatch.notifications, "permanent_failure_context")
    @patch.object(dispatch.mercure, "customer_email", side_effect=RuntimeError("client@example.fr secret-token"))
    def test_permanent_recipient_check_persists_bounded_lookup_failure(self, customer_email, context, record):
        self.add_target(due="2026-09-20")
        reference = dispatch._reference({
            "vehicle_id": "vehicle-99", "due_date": "2026-09-20", "days_before": 1,
        })
        context.return_value = {
            "incidentId": "e" * 32, "channel": "email", "category": "ct_due_reminder",
            "reference": reference, "permanentState": "open",
        }
        result = dispatch.permanent_recipient_check("e" * 32)
        self.assertFalse(result["ok"])
        self.assertEqual(result["recipientState"], "lookup_failed")
        record.assert_called_once_with("e" * 32, "lookup_failed")
        self.assertNotIn("client@example.fr", str(result))
        self.assertNotIn("secret-token", str(result))

    @patch.object(dispatch, "permanent_recipient_check")
    @patch.object(dispatch.notifications, "status")
    def test_background_recipient_refresh_checks_unresolved_reminders_without_delivery(self, status, check):
        status.return_value = {"permanentFailures": [
            {"incident_id": "1" * 32, "channel": "email", "category": "ct_due_reminder", "permanent_state": "open"},
            {"incident_id": "2" * 32, "channel": "email", "category": "ct_due_reminder", "permanent_state": "acknowledged"},
            {"incident_id": "3" * 32, "channel": "push", "category": "ct_due_reminder", "permanent_state": "open"},
            {"incident_id": "4" * 32, "channel": "email", "category": "ct_due_reminder", "permanent_state": "resolved"},
        ]}
        check.side_effect = [
            {"ok": True, "recipientState": "unchanged", "transitionedToChanged": False},
            {"ok": True, "recipientState": "changed", "transitionedToChanged": True},
        ]
        result = dispatch.refresh_permanent_recipient_checks()
        self.assertEqual(result["checked"], 2)
        self.assertEqual(result["unchanged"], 1)
        self.assertEqual(result["changed"], 1)
        self.assertEqual(result["newlyChanged"], 1)
        self.assertEqual(result["skipped"], 2)
        self.assertEqual(check.call_count, 2)
        raw = dispatch._meta("last_permanent_recipient_refresh", "")
        self.assertIn('"checked":2', raw)

    @patch.object(dispatch.notifications, "send_email")
    @patch.object(dispatch.notifications, "permanent_failure_recipient_state", return_value={
        "ok": True, "incidentId": "c" * 32, "recipientState": "unchanged", "permanentState": "open",
    })
    @patch.object(dispatch.notifications, "permanent_failure_context")
    @patch.object(dispatch.mercure, "customer_email", return_value="same@example.fr")
    @patch.object(dispatch.mail, "preflight")
    def test_permanent_recipient_retry_never_sends_when_recipient_is_unchanged(
        self, preflight, customer_email, context, compare, send_email
    ):
        self.add_target(due="2026-09-20")
        reference = dispatch._reference({
            "vehicle_id": "vehicle-99", "due_date": "2026-09-20", "days_before": 1,
        })
        context.return_value = {
            "incidentId": "c" * 32, "channel": "email", "category": "ct_due_reminder",
            "reference": reference, "permanentState": "open",
        }
        result = dispatch.permanent_recipient_retry("c" * 32)
        self.assertFalse(result["ok"])
        self.assertEqual(result["state"], "recipient_unchanged")
        preflight.assert_not_called()
        send_email.assert_not_called()



if __name__ == "__main__":
    unittest.main()
