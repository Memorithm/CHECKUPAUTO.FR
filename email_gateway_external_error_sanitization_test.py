import unittest
from unittest.mock import Mock

import email_gateway as mail


class GmailExternalDiagnosticsTest(unittest.TestCase):
    def test_unknown_provider_text_and_retry_header_are_not_persisted(self):
        response = Mock()
        response.status_code = 400
        response.headers = {"Retry-After": "sensitive-marker-42"}
        response.json.return_value = {
            "error": {
                "errors": [{"reason": "client@example.fr"}],
                "status": "SENSITIVE_MARKER_42",
            }
        }

        error = mail._gmail_response_error(response)

        self.assertEqual(error.reason, "gmail_http_error")
        self.assertEqual(error.retry_after, "")
        self.assertFalse(error.retryable)
        self.assertFalse(error.configuration_error)
        self.assertTrue(error.permanent)
        rendered = " ".join((str(error), error.reason, error.retry_after))
        self.assertNotIn("client@example.fr", rendered)
        self.assertNotIn("clientexample.fr", rendered)
        self.assertNotIn("sensitive-marker-42", rendered.lower())

    def test_known_transient_reason_and_numeric_retry_after_are_preserved(self):
        response = Mock()
        response.status_code = 403
        response.headers = {"Retry-After": "120"}
        response.json.return_value = {
            "error": {"errors": [{"reason": "userRateLimitExceeded"}]}
        }

        error = mail._gmail_response_error(response)

        self.assertEqual(error.reason, "userRateLimitExceeded")
        self.assertEqual(error.retry_after, "120")
        self.assertTrue(error.retryable)
        self.assertFalse(error.configuration_error)
        self.assertFalse(error.permanent)

    def test_known_canonical_status_maps_to_bounded_reason(self):
        response = Mock()
        response.status_code = 429
        response.headers = {}
        response.json.return_value = {
            "error": {"status": "RESOURCE_EXHAUSTED"}
        }

        error = mail._gmail_response_error(response)

        self.assertEqual(error.reason, "quotaExceeded")
        self.assertTrue(error.retryable)
        self.assertFalse(error.configuration_error)
        self.assertFalse(error.permanent)


if __name__ == "__main__":
    unittest.main()
