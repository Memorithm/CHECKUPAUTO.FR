import datetime
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

import mobile_reminder_dispatch as dispatch


class MobileReminderDispatchTest(unittest.TestCase):
    def setUp(self):
        self.now = datetime.datetime(2026, 9, 19, 10, 0, tzinfo=ZoneInfo("Europe/Paris"))
        self.row = {
            "installation_id": "60cf7ccf-4297-41f4-b76b-c0bd44dbe3d1",
            "deadline_id": "e62c0b27-2141-4f5c-b2f4-1e458aa6a6ca",
            "due_date": "2026-09-26",
            "device_token": "ab" * 32,
            "environment": "sandbox",
        }

    @patch.object(dispatch.mobile_devices, "due_targets")
    def test_eligible_uses_only_central_policy_days(self, due_targets):
        due_targets.return_value = [self.row]
        rows = dispatch._eligible(self.now)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["days_before"], 7)

    @patch.object(dispatch.mobile_devices, "due_targets")
    @patch.object(dispatch.notifications, "send_push")
    @patch.object(dispatch.apns_gateway, "status", return_value={"configured": True})
    @patch.object(dispatch, "_enabled", return_value=False)
    def test_activation_gate_prevents_push(self, enabled, status, send_push, due_targets):
        due_targets.return_value = [self.row]
        result = dispatch.process_once(self.now)
        self.assertEqual(result["state"], "waiting_activation")
        send_push.assert_not_called()

    @patch.object(dispatch.mobile_devices, "due_targets")
    @patch.object(dispatch.notifications, "send_push")
    @patch.object(dispatch.apns_gateway, "status", return_value={"configured": True})
    @patch.object(dispatch, "_enabled", return_value=True)
    def test_push_uses_device_environment_and_opaque_deadline_data(self, enabled, status, send_push, due_targets):
        due_targets.return_value = [self.row]
        send_push.return_value = {"status": "sent", "alreadySent": False, "inFlight": False}
        result = dispatch.process_once(self.now)
        self.assertEqual(result["sent"], 1)
        _, _, _ = send_push.call_args.args
        kwargs = send_push.call_args.kwargs
        self.assertEqual(kwargs["environment"], "sandbox")
        self.assertEqual(kwargs["data"], {
            "deadlineId": self.row["deadline_id"],
            "dueDate": self.row["due_date"],
            "daysBefore": 7,
        })
        self.assertNotIn("registration", str(send_push.call_args).lower())

    @patch.object(dispatch.mobile_devices, "due_targets")
    @patch.object(dispatch.mobile_devices, "disable_invalid_token", return_value={"disabled": True})
    @patch.object(dispatch.notifications, "send_push")
    @patch.object(dispatch.apns_gateway, "status", return_value={"configured": True})
    @patch.object(dispatch, "_enabled", return_value=True)
    def test_unregistered_token_is_retired_without_retry_failure(self, enabled, status, send_push, disable, due_targets):
        due_targets.return_value = [self.row]
        send_push.side_effect = dispatch.apns_gateway.APNSError(410, "Unregistered")
        result = dispatch.process_once(self.now)
        self.assertTrue(result["ok"])
        self.assertEqual(result["state"], "active_tokens_retired")
        self.assertEqual(result["retiredTokens"], 1)
        disable.assert_called_once_with(self.row["installation_id"], self.row["device_token"], "apns:Unregistered")

    @patch.object(dispatch.mobile_devices, "due_targets")
    @patch.object(dispatch.notifications, "send_push")
    @patch.object(dispatch.apns_gateway, "status", return_value={"configured": True})
    @patch.object(dispatch, "_enabled", return_value=True)
    def test_provider_configuration_error_stops_batch(self, enabled, status, send_push, due_targets):
        second = dict(self.row); second["deadline_id"] = "936246c1-8932-4b6f-92b6-1ea591c09f96"
        due_targets.return_value = [self.row, second]
        send_push.side_effect = dispatch.apns_gateway.APNSError(400, "DeviceTokenNotForTopic")
        result = dispatch.process_once(self.now)
        self.assertFalse(result["ok"])
        self.assertEqual(result["state"], "provider_failure")
        self.assertEqual(result["providerFailures"], 1)
        self.assertEqual(send_push.call_count, 1)

    @patch.object(dispatch.mobile_devices, "due_targets")
    @patch.object(dispatch.notifications, "send_push")
    @patch.object(dispatch.apns_gateway, "status", return_value={"configured": True})
    @patch.object(dispatch, "_enabled", return_value=True)
    def test_transient_apns_failure_remains_retryable(self, enabled, status, send_push, due_targets):
        due_targets.return_value = [self.row]
        send_push.side_effect = dispatch.apns_gateway.APNSError(503, "ServiceUnavailable")
        result = dispatch.process_once(self.now)
        self.assertEqual(result["state"], "partial_failure")
        self.assertEqual(result["transientFailures"], 1)
        self.assertEqual(result["retiredTokens"], 0)

    @patch.object(dispatch.mobile_devices, "due_targets")
    @patch.object(dispatch.notifications, "send_push")
    @patch.object(dispatch.apns_gateway, "status", return_value={"configured": False})
    @patch.object(dispatch, "_enabled", return_value=True)
    def test_missing_apns_credentials_is_safe(self, enabled, status, send_push, due_targets):
        due_targets.return_value = [self.row]
        result = dispatch.process_once(self.now)
        self.assertEqual(result["state"], "waiting_apns_credentials")
        send_push.assert_not_called()


if __name__ == "__main__":
    unittest.main()
