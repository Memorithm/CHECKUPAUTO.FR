import datetime
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import integration_hub as hub


class IntegrationHubBusinessProfileProbeTest(unittest.TestCase):
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
            "scope": hub.BUSINESS_PROFILE_SCOPE,
            "expires_at": (
                datetime.datetime.now(datetime.timezone.utc)
                + datetime.timedelta(hours=1)
            ).isoformat(),
        })

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def _response(status=200, payload=None, headers=None):
        response = Mock()
        response.status_code = status
        response.headers = headers or {}
        response.json.return_value = payload if payload is not None else {}
        return response

    def test_account_id_is_normalized_to_google_resource_name(self):
        saved = hub.save_settings({"businessAccountId": "123456"})
        self.assertEqual(saved["businessAccountId"], "accounts/123456")
        self.assertEqual(hub.settings()["businessAccountId"], "accounts/123456")

    def test_account_id_rejects_non_numeric_resource(self):
        for invalid in ("accounts/demo", "locations/123", "accounts/12/34", "１２３"):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(hub.IntegrationError, "Business Profile invalide"):
                    hub.save_settings({"businessAccountId": invalid})

    def test_account_probe_uses_account_management_read_endpoint(self):
        hub.save_settings({"businessAccountId": "accounts/123456"})
        response = self._response(payload={"name": "accounts/123456", "type": "PERSONAL"})
        with patch("integration_hub.requests.get", return_value=response) as get:
            result = hub.business_profile_account_probe()
        self.assertEqual(result, {"connected": True, "verification": "verified"})
        get.assert_called_once_with(
            "https://mybusinessaccountmanagement.googleapis.com/v1/accounts/123456",
            headers={"Authorization": "Bearer test-access"},
            timeout=20,
        )
        self.assertNotIn("test-access", str(result))

    def test_admin_status_marks_business_profile_verified_after_api_success(self):
        hub.save_settings({"businessAccountId": "accounts/123456"})
        response = self._response(payload={"name": "accounts/123456"})
        with patch("integration_hub.requests.get", return_value=response):
            state = hub.status({}, "https://www.checkupauto.fr")
        row = next(item for item in state["connectors"] if item["id"] == "business_profile")
        self.assertTrue(row["connected"])
        self.assertEqual(row["verification"], "verified")
        self.assertEqual(row["detail"], "API Google Business Profile vérifiée")

    def test_denied_account_cannot_remain_connected(self):
        hub.save_settings({"businessAccountId": "accounts/123456"})
        with patch(
            "integration_hub.requests.get",
            return_value=self._response(status=403),
        ):
            state = hub.status({}, "https://www.checkupauto.fr")
        row = next(item for item in state["connectors"] if item["id"] == "business_profile")
        self.assertFalse(row["connected"])
        self.assertEqual(row["state"], "attention")
        self.assertEqual(row["verification"], "failed")
        self.assertIn("compte non accessible", row["detail"])

    def test_transient_failure_is_unavailable_and_does_not_leak_exception(self):
        hub.save_settings({"businessAccountId": "accounts/123456"})
        with patch(
            "integration_hub.requests.get",
            side_effect=hub.requests.ConnectionError("credential=do-not-expose"),
        ):
            state = hub.status({}, "https://www.checkupauto.fr")
        row = next(item for item in state["connectors"] if item["id"] == "business_profile")
        self.assertFalse(row["connected"])
        self.assertEqual(row["verification"], "unavailable")
        self.assertNotIn("do-not-expose", row["detail"])

    def test_retry_after_is_preserved_for_transient_google_failure(self):
        hub.save_settings({"businessAccountId": "accounts/123456"})
        response = self._response(status=503, headers={"Retry-After": "45"})
        with patch("integration_hub.requests.get", return_value=response):
            with self.assertRaises(hub.IntegrationHTTPError) as caught:
                hub.business_profile_account_probe()
        self.assertEqual(caught.exception.status, 503)
        self.assertEqual(caught.exception.retry_after, "45")
        self.assertTrue(caught.exception.retryable)


if __name__ == "__main__":
    unittest.main()
