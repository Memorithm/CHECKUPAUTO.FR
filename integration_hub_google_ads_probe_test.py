import datetime
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import integration_hub as hub


class IntegrationHubGoogleAdsProbeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        hub.PRIVATE_DIR = root
        hub.INTEGRATION_DIR = root / "integrations"
        hub.CLIENT_FILE = hub.INTEGRATION_DIR / "google-oauth-client.json"
        hub.TOKEN_FILE = hub.INTEGRATION_DIR / "google-oauth-token.json"
        hub.SETTINGS_FILE = hub.INTEGRATION_DIR / "google-settings.json"
        hub.STATE_FILE = hub.INTEGRATION_DIR / "google-oauth-state.json"
        hub.save_oauth_client({
            "web": {
                "client_id": "client-id.apps.googleusercontent.com",
                "client_secret": "test-secret",
                "token_uri": hub.TOKEN_URL,
                "redirect_uris": [
                    "https://www.checkupauto.fr/api/integrations/google/oauth/callback"
                ],
            }
        })
        hub._atomic_json(hub.TOKEN_FILE, {
            "access_token": "test-access",
            "scope": hub.GOOGLE_ADS_SCOPE,
            "expires_at": (
                datetime.datetime.now(datetime.timezone.utc)
                + datetime.timedelta(hours=1)
            ).isoformat(),
        })
        hub.save_settings({"googleAdsDeveloperToken": "test-developer-token"})

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def _response(status=200, payload=None, headers=None):
        response = Mock()
        response.status_code = status
        response.headers = headers or {}
        response.json.return_value = payload if payload is not None else {}
        return response

    def test_probe_uses_accessible_customers_without_exposing_ids_or_secrets(self):
        response = self._response(payload={
            "resourceNames": ["customers/1234567890", "customers/9876543210"]
        })
        with patch("integration_hub.requests.get", return_value=response) as get:
            result = hub.google_ads_access_probe()
        get.assert_called_once_with(
            "https://googleads.googleapis.com/v25/customers:listAccessibleCustomers",
            headers={
                "Authorization": "Bearer test-access",
                "developer-token": "test-developer-token",
            },
            timeout=20,
        )
        self.assertTrue(result["usable"])
        self.assertEqual(result["accessibleCustomerCount"], 2)
        self.assertNotIn("1234567890", str(result))
        self.assertNotIn("test-access", str(result))
        self.assertNotIn("test-developer-token", str(result))

    def test_status_marks_ads_verified_only_after_remote_success(self):
        with patch(
            "integration_hub.requests.get",
            return_value=self._response(payload={"resourceNames": ["customers/1234567890"]}),
        ):
            state = hub.status({}, "https://www.checkupauto.fr")
        row = next(item for item in state["connectors"] if item["id"] == "google_ads")
        self.assertTrue(row["connected"])
        self.assertEqual(row["verification"], "verified")
        self.assertEqual(row["detail"], "API Google Ads vérifiée")
        self.assertEqual(row["probe"], {"accessibleCustomerCount": 1})

    def test_no_accessible_ads_account_is_not_operationally_connected(self):
        with patch(
            "integration_hub.requests.get",
            return_value=self._response(payload={"resourceNames": []}),
        ):
            state = hub.status({}, "https://www.checkupauto.fr")
        row = next(item for item in state["connectors"] if item["id"] == "google_ads")
        self.assertFalse(row["connected"])
        self.assertEqual(row["state"], "attention")
        self.assertEqual(row["verification"], "failed")
        self.assertIn("aucun compte accessible", row["detail"])
        self.assertEqual(row["probe"], {"accessibleCustomerCount": 0})

    def test_denied_developer_token_cannot_remain_connected(self):
        with patch(
            "integration_hub.requests.get",
            return_value=self._response(status=403),
        ):
            state = hub.status({}, "https://www.checkupauto.fr")
        row = next(item for item in state["connectors"] if item["id"] == "google_ads")
        self.assertFalse(row["connected"])
        self.assertEqual(row["state"], "attention")
        self.assertEqual(row["verification"], "failed")
        self.assertNotIn("test-developer-token", row["detail"])

    def test_transient_failure_is_unavailable_without_leaking_error(self):
        with patch(
            "integration_hub.requests.get",
            side_effect=hub.requests.ConnectionError("developer-token=do-not-expose"),
        ):
            state = hub.status({}, "https://www.checkupauto.fr")
        row = next(item for item in state["connectors"] if item["id"] == "google_ads")
        self.assertFalse(row["connected"])
        self.assertEqual(row["verification"], "unavailable")
        self.assertNotIn("do-not-expose", row["detail"])

    def test_retryable_google_status_preserves_bounded_retry_after(self):
        retry_after = "2" * 200
        response = self._response(status=503, headers={"Retry-After": retry_after})
        with patch("integration_hub.requests.get", return_value=response):
            with self.assertRaises(hub.IntegrationHTTPError) as caught:
                hub.google_ads_access_probe()
        self.assertEqual(caught.exception.status, 503)
        self.assertTrue(caught.exception.retryable)
        self.assertEqual(caught.exception.retry_after, retry_after[:80])


if __name__ == "__main__":
    unittest.main()
