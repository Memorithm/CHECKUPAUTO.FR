import unittest
from unittest.mock import patch

import notification_preflight as preflight


class NotificationPreflightTest(unittest.TestCase):
    @patch.object(preflight.apns, "preflight")
    @patch.object(preflight.email, "preflight")
    def test_combines_non_delivering_transport_diagnostics(self, email_probe, apns_probe):
        email_probe.return_value = {
            "ok": False,
            "requested": "auto",
            "activeTransport": "none",
            "state": "awaiting_configuration",
            "transports": [
                {"transport": "smtp-relay", "ready": False, "state": "awaiting_configuration", "reason": "sender_missing"},
                {"transport": "gmail-api", "ready": False, "state": "awaiting_configuration", "reason": "gmail_send_scope_missing"},
            ],
        }
        apns_probe.return_value = {
            "configured": False,
            "transport": "apns-http2",
            "state": "awaiting_credentials",
            "ready": False,
            "reason": "credentials_missing",
            "keyValid": False,
        }
        result = preflight.run()
        self.assertTrue(result["ok"])
        self.assertEqual(result["sendsPerformed"], 0)
        self.assertEqual([x["transport"] for x in result["transports"]], ["smtp-relay", "gmail-api", "apns-http2"])
        self.assertNotIn("token", str(result).lower())
        self.assertNotIn("password", str(result).lower())


if __name__ == "__main__":
    unittest.main()
