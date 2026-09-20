import unittest
from unittest.mock import patch

import apns_gateway as apns
import notification_broker as broker


class APNSBoundaryTest(unittest.TestCase):
    def test_direct_apns_error_construction_sanitizes_untrusted_fields(self):
        error = apns.APNSError(
            400,
            "client@example.fr sensitive-marker-42",
            apns_id="client@example.fr-sensitive-marker-42",
            retry_after="sensitive-marker-42",
        )

        self.assertEqual(error.reason, apns.UNKNOWN_PROVIDER_REASON)
        self.assertEqual(error.apns_id, "")
        self.assertEqual(error.retry_after, "")
        rendered = str(error)
        self.assertNotIn("client@example.fr", rendered)
        self.assertNotIn("sensitive-marker-42", rendered)

    @patch.object(apns, "status", return_value={"configured": False})
    @patch.object(apns, "_config", return_value={})
    def test_missing_apns_credentials_raise_typed_configuration_error(self, _config, _status):
        with self.assertRaises(apns.APNSError) as caught:
            apns.send("ab" * 32, "Rappel", "Message")

        error = caught.exception
        self.assertEqual(error.reason, "CredentialsMissing")
        self.assertTrue(error.provider_error)
        self.assertFalse(error.retryable)
        self.assertEqual(broker._classify_failure(error), "configuration")

    def test_known_transient_error_remains_retryable_after_constructor_sanitization(self):
        error = apns.APNSError(503, "ServiceUnavailable", retry_after="60")

        self.assertEqual(error.reason, "ServiceUnavailable")
        self.assertEqual(error.retry_after, "60")
        self.assertTrue(error.retryable)
        self.assertFalse(error.provider_error)
        self.assertEqual(broker._classify_failure(error), "transient")


if __name__ == "__main__":
    unittest.main()
