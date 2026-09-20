import unittest
from unittest import mock

import security_alerts as alerts


class SecurityAlertDeliveryTest(unittest.TestCase):
    def test_delivery_requires_external_webhook(self):
        with mock.patch.dict(alerts.os.environ, {}, clear=True):
            status = alerts.delivery_status()
        self.assertFalse(status["configured"])
        self.assertFalse(status["ready"])
        self.assertEqual(status["state"], "awaiting_webhook")

    def test_delivery_rejects_private_endpoint(self):
        env = {
            "CYBERCHECK_SECURITY_ALERT_WEBHOOK": "https://alerts.example.invalid/hook",
            "CYBERCHECK_SECURITY_ALERT_SECRET": "test-secret",
        }
        with mock.patch.dict(alerts.os.environ, env, clear=True), mock.patch.object(
            alerts, "_resolve_endpoint_ips", return_value=["127.0.0.1"]
        ):
            status = alerts.delivery_status()
        self.assertFalse(status["ready"])
        self.assertEqual(status["state"], "private_endpoint_rejected")

    def test_delivery_requires_hmac_secret(self):
        env = {"CYBERCHECK_SECURITY_ALERT_WEBHOOK": "https://alerts.example.invalid/hook"}
        with mock.patch.dict(alerts.os.environ, env, clear=True), mock.patch.object(
            alerts, "_resolve_endpoint_ips", return_value=["93.184.216.34"]
        ):
            status = alerts.delivery_status()
        self.assertTrue(status["configured"])
        self.assertFalse(status["ready"])
        self.assertEqual(status["state"], "awaiting_signing_secret")

    def test_ready_delivery_is_signed_and_does_not_follow_redirects(self):
        env = {
            "CYBERCHECK_SECURITY_ALERT_WEBHOOK": "https://alerts.example.invalid/hook",
            "CYBERCHECK_SECURITY_ALERT_SECRET": "test-secret",
        }
        response = mock.Mock()
        response.status_code = 204
        response.raise_for_status.return_value = None
        with mock.patch.dict(alerts.os.environ, env, clear=True), mock.patch.object(
            alerts, "_resolve_endpoint_ips", return_value=["93.184.216.34"]
        ), mock.patch.object(alerts.requests, "post", return_value=response) as post:
            self.assertTrue(alerts._deliver({"id": 7, "level": "high"}))
        _, kwargs = post.call_args
        self.assertFalse(kwargs["allow_redirects"])
        self.assertEqual(kwargs["timeout"], 8)
        self.assertTrue(kwargs["headers"]["X-CyberCheck-Signature"].startswith("sha256="))

    def test_invalid_webhook_syntax_does_not_resolve(self):
        env = {
            "CYBERCHECK_SECURITY_ALERT_WEBHOOK": "http://127.0.0.1/hook#fragment",
            "CYBERCHECK_SECURITY_ALERT_SECRET": "test-secret",
        }
        with mock.patch.dict(alerts.os.environ, env, clear=True), mock.patch.object(
            alerts, "_resolve_endpoint_ips"
        ) as resolve:
            status = alerts.delivery_status()
        self.assertEqual(status["state"], "invalid_endpoint")
        resolve.assert_not_called()


if __name__ == "__main__":
    unittest.main()
