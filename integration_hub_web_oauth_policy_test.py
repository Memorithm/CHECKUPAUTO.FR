import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

import integration_hub as hub

CALLBACK = "https://www.checkupauto.fr/api/integrations/google/oauth/callback"


class IntegrationHubWebOAuthPolicyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        hub.PRIVATE_DIR = root
        hub.INTEGRATION_DIR = root / "integrations"
        hub.CLIENT_FILE = hub.INTEGRATION_DIR / "google-oauth-client.json"
        hub.TOKEN_FILE = hub.INTEGRATION_DIR / "google-oauth-token.json"
        hub.SETTINGS_FILE = hub.INTEGRATION_DIR / "google-settings.json"
        hub.STATE_FILE = hub.INTEGRATION_DIR / "google-oauth-state.json"

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def web_client(redirects=None):
        return {
            "web": {
                "client_id": "client-id.apps.googleusercontent.com",
                "client_secret": "secret-value",
                "project_id": "cybercheck-test",
                "token_uri": hub.TOKEN_URL,
                "redirect_uris": list(redirects if redirects is not None else [CALLBACK]),
            }
        }

    def test_rejects_installed_desktop_client(self):
        with self.assertRaisesRegex(hub.IntegrationError, "Application Web"):
            hub.save_oauth_client({"installed": {
                "client_id": "desktop.apps.googleusercontent.com",
                "client_secret": "secret-value",
                "token_uri": hub.TOKEN_URL,
                "redirect_uris": ["http://localhost"],
            }})
        self.assertFalse(hub.CLIENT_FILE.exists())

    def test_rejects_flat_untyped_client(self):
        with self.assertRaisesRegex(hub.IntegrationError, "configuration web"):
            hub.save_oauth_client({
                "client_id": "legacy.apps.googleusercontent.com",
                "client_secret": "secret-value",
                "token_uri": hub.TOKEN_URL,
            })
        self.assertFalse(hub.CLIENT_FILE.exists())

    def test_web_client_requires_declared_redirect_uri(self):
        with self.assertRaisesRegex(hub.IntegrationError, "URI de redirection"):
            hub.save_oauth_client(self.web_client([]))

    def test_saved_web_client_reports_secret_free_policy_state(self):
        info = hub.save_oauth_client(self.web_client())
        self.assertTrue(info["configured"])
        self.assertTrue(info["webClientVerified"])
        self.assertEqual(info["redirectUriCount"], 1)
        self.assertNotIn("client_secret", info)

    def test_status_distinguishes_web_shape_from_exact_callback_authorization(self):
        hub.save_oauth_client(self.web_client(["https://other.example/api/integrations/google/oauth/callback"]))
        client = hub.status({}, "https://www.checkupauto.fr")["oauthClient"]
        self.assertTrue(client["webClientVerified"])
        self.assertFalse(client["redirectUriAllowed"])
        self.assertEqual(client["redirectUriCount"], 1)

    def test_status_marks_exact_checkupauto_callback_allowed(self):
        hub.save_oauth_client(self.web_client())
        client = hub.status({}, "https://www.checkupauto.fr")["oauthClient"]
        self.assertTrue(client["webClientVerified"])
        self.assertTrue(client["redirectUriAllowed"])

    def test_authorization_uses_exact_registered_callback(self):
        hub.save_oauth_client(self.web_client())
        result = hub.create_authorization_url("https://www.checkupauto.fr", ["analytics"])
        params = parse_qs(urlparse(result["authorizationUrl"]).query)
        self.assertEqual(params["redirect_uri"], [CALLBACK])

    def test_authorization_rejects_unregistered_callback_before_state_write(self):
        hub.save_oauth_client(self.web_client())
        with self.assertRaisesRegex(hub.IntegrationError, "n’est pas autorisée"):
            hub.create_authorization_url("https://staging.checkupauto.fr", ["analytics"])
        self.assertFalse(hub.STATE_FILE.exists())

    def test_legacy_normalized_client_can_refresh_but_cannot_start_new_authorization(self):
        hub._atomic_json(hub.CLIENT_FILE, {
            "client_id": "legacy.apps.googleusercontent.com",
            "client_secret": "legacy-secret",
            "project_id": "legacy-project",
            "token_uri": hub.TOKEN_URL,
        })
        hub._atomic_json(hub.TOKEN_FILE, {
            "refresh_token": "refresh",
            "scope": "https://www.googleapis.com/auth/analytics.readonly",
        })
        self.assertTrue(hub.oauth_health()["usable"])
        self.assertFalse(hub.oauth_client_info()["webClientVerified"])
        with self.assertRaisesRegex(hub.IntegrationError, "Application Web"):
            hub.create_authorization_url("https://www.checkupauto.fr", ["analytics"])
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"access_token": "new-access", "expires_in": 3600}
        with patch("integration_hub.requests.post", return_value=response):
            token = hub.google_access_token(
                ["https://www.googleapis.com/auth/analytics.readonly"], force_refresh=True
            )
        self.assertEqual(token, "new-access")

    def test_callback_fails_closed_if_web_client_policy_is_lost(self):
        hub.save_oauth_client(self.web_client())
        auth = hub.create_authorization_url("https://www.checkupauto.fr", ["analytics"])
        state = parse_qs(urlparse(auth["authorizationUrl"]).query)["state"][0]
        hub._atomic_json(hub.CLIENT_FILE, {
            "client_id": "legacy.apps.googleusercontent.com",
            "client_secret": "legacy-secret",
            "token_uri": hub.TOKEN_URL,
        })
        with patch("integration_hub.requests.post") as post:
            with self.assertRaisesRegex(hub.IntegrationError, "client OAuth Google Web"):
                hub.handle_oauth_callback("https://www.checkupauto.fr", state, "code")
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
