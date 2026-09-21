import datetime
import unittest
from unittest import mock

import mobile_reminder_dispatch as mobile
import reminder_dispatch as email_reminders
import review_followup as reviews


class PrivacyChannelEnforcementTest(unittest.TestCase):
    def test_email_reminder_is_not_sent_when_subject_is_suppressed(self):
        row = {
            "vehicle_id": "veh-1",
            "client_kind": "account",
            "client_id": "42",
            "due_date": "2026-10-01",
            "appointment_id": "",
            "days_before": 7,
        }
        now = datetime.datetime(2026, 9, 24, 12, 0, tzinfo=datetime.timezone.utc)
        with mock.patch.object(email_reminders, "init_db"), \
             mock.patch.object(email_reminders, "_set_meta"), \
             mock.patch.object(email_reminders, "_eligible", return_value=[row]), \
             mock.patch.object(email_reminders.mail, "configured", return_value=True), \
             mock.patch.object(email_reminders.mail, "preflight", return_value={"ok": True}), \
             mock.patch.object(email_reminders.mail, "valid_email", return_value=True), \
             mock.patch.object(
                 email_reminders.mercure, "customer_email", return_value="alice@example.test"
             ), \
             mock.patch.object(email_reminders.privacy, "any_suppressed", return_value=True), \
             mock.patch.object(email_reminders.notifications, "send_email") as send:
            result = email_reminders.process_once(now, do_sync=False)

        self.assertEqual(result["privacySuppressed"], 1)
        self.assertEqual(result["sent"], 0)
        self.assertEqual(result["state"], "active_with_privacy_suppressions")
        send.assert_not_called()

    def test_review_request_is_not_sent_when_email_is_suppressed(self):
        row = {
            "id": "rdv-1",
            "honored": True,
            "finished": True,
            "name": "Alice Martin",
            "email": "alice@example.test",
            "dateRdv": "2026-09-21 10:00",
        }
        eligible_at = reviews._now() - datetime.timedelta(hours=1)
        with mock.patch.object(reviews.mercure, "session_status", return_value={"connected": True}), \
             mock.patch.object(
                 reviews.mercure,
                 "native_review_email_status",
                 return_value={"nativeFavorableOnlyEmailEnabled": False},
             ), \
             mock.patch.object(reviews.mail, "configured", return_value=True), \
             mock.patch.object(reviews.mail, "preflight", return_value={"ok": True}), \
             mock.patch.object(reviews.mail, "valid_email", return_value=True), \
             mock.patch.object(reviews, "_review_url", return_value="https://example.test/review"), \
             mock.patch.object(reviews, "_parse_dt", return_value=eligible_at), \
             mock.patch.object(reviews.mercure, "review_followup_rows", return_value=[row]), \
             mock.patch.object(reviews.privacy, "is_suppressed", return_value=True), \
             mock.patch.object(reviews, "_state", return_value=None), \
             mock.patch.object(reviews.notifications, "send_email") as send:
            result = reviews.process_once()

        self.assertEqual(result["privacySuppressed"], 1)
        self.assertEqual(result["sent"], 0)
        send.assert_not_called()

    def test_push_reminder_is_not_sent_when_installation_is_suppressed(self):
        row = {
            "installation_id": "11111111-1111-1111-1111-111111111111",
            "deadline_id": "d1",
            "due_date": "2026-10-01",
            "days_before": 7,
            "device_token": "a" * 64,
            "environment": "production",
        }
        now = datetime.datetime(2026, 9, 24, 12, 0, tzinfo=datetime.timezone.utc)
        with mock.patch.object(mobile, "_eligible", return_value=[row]), \
             mock.patch.object(mobile, "_enabled", return_value=True), \
             mock.patch.object(mobile.apns_gateway, "status", return_value={"configured": True}), \
             mock.patch.object(mobile.privacy, "is_suppressed", return_value=True), \
             mock.patch.object(mobile.notifications, "send_push") as send:
            result = mobile.process_once(now)

        self.assertEqual(result["privacySuppressed"], 1)
        self.assertEqual(result["sent"], 0)
        self.assertEqual(result["state"], "active_with_privacy_suppressions")
        send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
