import datetime
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import integration_hub as hub


class IntegrationHubTagManagerProbeTest(unittest.TestCase):
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
            "scope": hub.TAG_MANAGER_SCOPE,
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

    @staticmethod
    def _account(account_id="654321"):
        return {
            "path": f"accounts/{account_id}",
            "accountId": account_id,
            "name": "CheckupAuto",
        }

    def test_setting_is_normalized_to_account_resource_name(self):
        hub.save_settings({"tagManagerAccountId": "654321"})
        self.assertEqual(hub.settings()["tagManagerAccountId"], "accounts/654321")
        hub.save_settings({"tagManagerAccountId": "accounts/987654"})
        self.assertEqual(hub.settings()["tagManagerAccountId"], "accounts/987654")
        for invalid in ("accounts/", "accounts/12/34", "12/34"):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(hub.IntegrationError, "Tag Manager invalide"):
                    hub.save_settings({"tagManagerAccountId": invalid})

    def test_probe_uses_read_only_account_get_endpoint(self):
        hub.save_settings({"tagManagerAccountId": "accounts/654321"})
        response = self._response(payload=self._account())
        with patch("integration_hub.requests.get", return_value=response) as get:
            result = hub.tag_manager_account_probe()
        self.assertTrue(result["connected"])
        self.assertEqual(result["verification"], "verified")
        get.assert_called_once_with(
            "https://tagmanager.googleapis.com/tagmanager/v2/accounts/654321",
            headers={"Authorization": "Bearer test-access"},
            timeout=20,
        )
        self.assertNotIn("test-access", str(result))

    def test_status_marks_tag_manager_verified_only_after_api_success(self):
        hub.save_settings({"tagManagerAccountId": "accounts/654321"})
        with patch(
            "integration_hub.requests.get",
            return_value=self._response(payload=self._account()),
        ):
            state = hub.status({}, "https://www.checkupauto.fr")
        row = next(item for item in state["connectors"] if item["id"] == "tag_manager")
        self.assertTrue(row["connected"])
        self.assertEqual(row["verification"], "verified")
        self.assertEqual(row["detail"], "API Google Tag Manager vérifiée")

    def test_denied_account_cannot_remain_connected(self):
        hub.save_settings({"tagManagerAccountId": "accounts/654321"})
        with patch(
            "integration_hub.requests.get",
            return_value=self._response(status=403),
        ):
            state = hub.status({}, "https://www.checkupauto.fr")
        row = next(item for item in state["connectors"] if item["id"] == "tag_manager")
        self.assertFalse(row["connected"])
        self.assertEqual(row["state"], "attention")
        self.assertEqual(row["verification"], "failed")
        self.assertIn("compte non accessible", row["detail"])

    def test_transient_failure_is_unavailable_without_leaking_error(self):
        hub.save_settings({"tagManagerAccountId": "accounts/654321"})
        with patch(
            "integration_hub.requests.get",
            side_effect=hub.requests.ConnectionError("token=do-not-expose"),
        ):
            state = hub.status({}, "https://www.checkupauto.fr")
        row = next(item for item in state["connectors"] if item["id"] == "tag_manager")
        self.assertFalse(row["connected"])
        self.assertEqual(row["verification"], "unavailable")
        self.assertNotIn("do-not-expose", row["detail"])

    def test_retryable_google_status_preserves_bounded_retry_after(self):
        hub.save_settings({"tagManagerAccountId": "accounts/654321"})
        response = self._response(status=503, headers={"Retry-After": "120"})
        with patch("integration_hub.requests.get", return_value=response):
            with self.assertRaises(hub.IntegrationHTTPError) as caught:
                hub.tag_manager_account_probe()
        self.assertEqual(caught.exception.status, 503)
        self.assertEqual(caught.exception.retry_after, "120")
        self.assertTrue(caught.exception.retryable)


if __name__ == "__main__":
    unittest.main()
