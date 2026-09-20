import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

import integration_hub as hub


class IntegrationHubExternalErrorSanitizationTest(unittest.TestCase):
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
                "client_secret": "private-client-secret",
                "project_id": "cybercheck-test",
                "token_uri": hub.TOKEN_URL,
            }
        })

    def tearDown(self):
        self.tmp.cleanup()

    def _pending_state(self):
        auth = hub.create_authorization_url(
            "https://www.checkupauto.fr",
            ["analytics"],
        )
        return parse_qs(urlparse(auth["authorizationUrl"]).query)["state"][0]

    def test_callback_provider_error_does_not_echo_external_text(self):
        external = "access_denied client@example.fr bearer-super-secret"
        with self.assertRaises(hub.IntegrationError) as caught:
            hub.handle_oauth_callback(
                "https://www.checkupauto.fr",
                "ignored",
                "",
                external,
            )
        message = str(caught.exception)
        self.assertEqual(message, "Google a refusé l’autorisation OAuth.")
        self.assertNotIn("client@example.fr", message)
        self.assertNotIn("bearer-super-secret", message)
        self.assertNotIn("access_denied", message)

    def test_token_exchange_error_body_is_not_exposed(self):
        state = self._pending_state()
        response = Mock()
        response.status_code = 400
        response.headers = {"Retry-After": "45"}
        response.json.return_value = {
            "error": "invalid_grant",
            "error_description": "client@example.fr bearer-super-secret",
        }
        response.text = "raw bearer-super-secret"
        with patch("integration_hub.requests.post", return_value=response):
            with self.assertRaises(hub.IntegrationHTTPError) as caught:
                hub.handle_oauth_callback(
                    "https://www.checkupauto.fr",
                    state,
                    "authorization-code",
                )
        exc = caught.exception
        self.assertEqual(str(exc), "Google a refusé l’échange OAuth.")
        self.assertEqual(exc.status, 400)
        self.assertEqual(exc.retry_after, "45")
        self.assertFalse(exc.retryable)
        self.assertNotIn("client@example.fr", str(exc))
        self.assertNotIn("bearer-super-secret", str(exc))

    def test_malformed_success_response_is_sanitized(self):
        state = self._pending_state()
        response = Mock()
        response.status_code = 200
        response.json.side_effect = ValueError(
            "malformed response for client@example.fr bearer-super-secret"
        )
        with patch("integration_hub.requests.post", return_value=response):
            with self.assertRaises(hub.IntegrationError) as caught:
                hub.handle_oauth_callback(
                    "https://www.checkupauto.fr",
                    state,
                    "authorization-code",
                )
        message = str(caught.exception)
        self.assertEqual(message, "Réponse OAuth Google invalide.")
        self.assertNotIn("client@example.fr", message)
        self.assertNotIn("bearer-super-secret", message)
        self.assertFalse(hub.TOKEN_FILE.exists())

    def test_success_response_without_access_token_is_rejected(self):
        state = self._pending_state()
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "expires_in": 3600,
            "scope": "https://www.googleapis.com/auth/analytics.readonly",
        }
        with patch("integration_hub.requests.post", return_value=response):
            with self.assertRaisesRegex(
                hub.IntegrationError,
                "jeton d’accès",
            ):
                hub.handle_oauth_callback(
                    "https://www.checkupauto.fr",
                    state,
                    "authorization-code",
                )
        self.assertFalse(hub.TOKEN_FILE.exists())
        self.assertTrue(hub.STATE_FILE.exists())


if __name__ == "__main__":
    unittest.main()
