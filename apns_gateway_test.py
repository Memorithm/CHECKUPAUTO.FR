import unittest
from unittest.mock import patch

import apns_gateway as apns


class Response:
    def __init__(self, status, reason, headers=None):
        self.status_code = status
        self._reason = reason
        self.headers = headers or {}

    def json(self):
        return {"reason": self._reason}


class APNSGatewayTest(unittest.TestCase):
    def test_unregistered_is_terminal_for_device_token(self):
        error = apns._error_from_response(Response(410, "Unregistered", {"apns-id": "id-1"}))
        self.assertTrue(error.token_invalid)
        self.assertFalse(error.retryable)
        self.assertFalse(error.provider_error)
        self.assertEqual(error.apns_id, "id-1")

    def test_bad_device_token_is_terminal(self):
        error = apns._error_from_response(Response(400, "BadDeviceToken"))
        self.assertTrue(error.token_invalid)
        self.assertFalse(error.provider_error)

    def test_topic_mismatch_is_provider_configuration_error_not_token_retirement(self):
        error = apns._error_from_response(Response(400, "DeviceTokenNotForTopic"))
        self.assertFalse(error.token_invalid)
        self.assertTrue(error.provider_error)
        self.assertFalse(error.retryable)

    @patch.object(apns.Path, "is_file", side_effect=PermissionError("denied"))
    def test_status_treats_unreadable_private_directory_as_unconfigured(self, _is_file):
        state = apns.status()
        self.assertFalse(state["configured"])
        self.assertFalse(state["keyPresent"])
        self.assertEqual(state["state"], "awaiting_credentials")

    def test_service_and_rate_limit_errors_are_retryable(self):
        for status, reason in ((429, "TooManyRequests"), (500, "InternalServerError"), (503, "ServiceUnavailable")):
            with self.subTest(status=status):
                error = apns._error_from_response(Response(status, reason, {"retry-after": "60"}))
                self.assertTrue(error.retryable)
                self.assertFalse(error.token_invalid)
                self.assertEqual(error.retry_after, "60")


if __name__ == "__main__":
    unittest.main()
