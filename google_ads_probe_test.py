import unittest
from unittest.mock import Mock

import requests

import google_ads_probe as probe


class GoogleAdsProbeTest(unittest.TestCase):
    @staticmethod
    def _response(status=200, payload=None, headers=None):
        response = Mock()
        response.status_code = status
        response.headers = headers or {}
        response.json.return_value = payload if payload is not None else {}
        return response

    def test_probe_uses_official_read_only_listing_endpoint(self):
        request_get = Mock(return_value=self._response(payload={
            "resourceNames": ["customers/1234567890", "customers/9876543210"]
        }))
        result = probe.verify_access(
            "test-access-token",
            "test-developer-token",
            request_get=request_get,
        )
        self.assertEqual(result, {
            "verification": "verified",
            "usable": True,
            "accessibleCustomerCount": 2,
        })
        request_get.assert_called_once_with(
            "https://googleads.googleapis.com/v25/customers:listAccessibleCustomers",
            headers={
                "Authorization": "Bearer test-access-token",
                "developer-token": "test-developer-token",
            },
            timeout=20,
        )
        self.assertNotIn("test-access-token", str(result))
        self.assertNotIn("test-developer-token", str(result))
        self.assertNotIn("1234567890", str(result))

    def test_empty_accessible_customer_set_is_verified_but_not_usable(self):
        result = probe.verify_access(
            "test-access-token",
            "test-developer-token",
            request_get=Mock(return_value=self._response(payload={"resourceNames": []})),
        )
        self.assertEqual(result["verification"], "verified")
        self.assertFalse(result["usable"])
        self.assertEqual(result["accessibleCustomerCount"], 0)

    def test_duplicate_customer_names_are_not_counted_twice(self):
        result = probe.verify_access(
            "test-access-token",
            "test-developer-token",
            request_get=Mock(return_value=self._response(payload={
                "resourceNames": ["customers/123", "customers/123"]
            })),
        )
        self.assertEqual(result["accessibleCustomerCount"], 1)

    def test_malformed_response_is_rejected_without_exposing_payload(self):
        with self.assertRaisesRegex(probe.GoogleAdsProbeError, "Réponse Google Ads invalide") as caught:
            probe.verify_access(
                "test-access-token",
                "test-developer-token",
                request_get=Mock(return_value=self._response(payload={
                    "resourceNames": ["customers/not-a-number-secret"]
                })),
            )
        self.assertNotIn("not-a-number-secret", str(caught.exception))

    def test_permission_failure_is_non_retryable_and_secret_safe(self):
        with self.assertRaises(probe.GoogleAdsProbeHTTPError) as caught:
            probe.verify_access(
                "test-access-token",
                "test-developer-token",
                request_get=Mock(return_value=self._response(status=403)),
            )
        self.assertEqual(caught.exception.status, 403)
        self.assertFalse(caught.exception.retryable)
        self.assertNotIn("test-access-token", str(caught.exception))
        self.assertNotIn("test-developer-token", str(caught.exception))

    def test_transient_google_failure_preserves_bounded_retry_after(self):
        retry_after = "1" * 200
        with self.assertRaises(probe.GoogleAdsProbeHTTPError) as caught:
            probe.verify_access(
                "test-access-token",
                "test-developer-token",
                request_get=Mock(return_value=self._response(
                    status=503,
                    headers={"Retry-After": retry_after},
                )),
            )
        self.assertEqual(caught.exception.status, 503)
        self.assertTrue(caught.exception.retryable)
        self.assertEqual(caught.exception.retry_after, retry_after[:80])

    def test_network_failure_does_not_leak_exception_detail(self):
        def fail(*args, **kwargs):
            raise requests.ConnectionError("developer-token=do-not-expose")

        with self.assertRaises(probe.GoogleAdsProbeHTTPError) as caught:
            probe.verify_access(
                "test-access-token",
                "test-developer-token",
                request_get=fail,
            )
        self.assertTrue(caught.exception.retryable)
        self.assertNotIn("do-not-expose", str(caught.exception))

    def test_credentials_are_required_before_any_request(self):
        request_get = Mock()
        for access, developer in (("", "developer"), ("access", "")):
            with self.subTest(access=bool(access), developer=bool(developer)):
                with self.assertRaises(probe.GoogleAdsProbeError):
                    probe.verify_access(access, developer, request_get=request_get)
        request_get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
