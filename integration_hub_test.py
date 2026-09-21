import datetime
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

import integration_hub as hub


class IntegrationHubTest(unittest.TestCase):
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

    def install_client(self):
        return hub.save_oauth_client({
            "web": {
                "client_id": "client-id.apps.googleusercontent.com",
                "client_secret": "super-secret",
                "project_id": "cybercheck-test",
                "token_uri": hub.TOKEN_URL,
                "redirect_uris": ["https://www.checkupauto.fr/api/integrations/google/oauth/callback"],
            }
        })

    def test_private_files_are_mode_600(self):
        self.install_client()
        mode = stat.S_IMODE(os.stat(hub.CLIENT_FILE).st_mode)
        self.assertEqual(mode, 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(hub.INTEGRATION_DIR).st_mode), 0o700)

    def test_rejects_untrusted_google_token_endpoint(self):
        with self.assertRaisesRegex(hub.IntegrationError, "token_uri OAuth Google non approuvée"):
            hub.save_oauth_client({
                "web": {
                    "client_id": "client-id.apps.googleusercontent.com",
                    "client_secret": "super-secret",
                    "token_uri": "https://attacker.invalid/token",
                }
            })
        self.assertFalse(hub.CLIENT_FILE.exists())

    def test_scope_only_token_is_not_an_authorized_session(self):
        hub._atomic_json(hub.TOKEN_FILE, {
            "scope": "https://www.googleapis.com/auth/analytics.readonly",
        })
        state = hub.status()
        analytics = next(x for x in state["connectors"] if x["id"] == "analytics")
        self.assertFalse(state["oauthAuthorized"])
        self.assertEqual(state["oauthHealth"]["state"], "awaiting_authorization")
        self.assertFalse(analytics["connected"])

    def test_expired_access_only_token_requires_reauthorization(self):
        hub._atomic_json(hub.TOKEN_FILE, {
            "access_token": "expired-access",
            "scope": "https://www.googleapis.com/auth/analytics.readonly",
            "expires_at": (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=1)).isoformat(),
        })
        state = hub.status()
        analytics = next(x for x in state["connectors"] if x["id"] == "analytics")
        self.assertFalse(state["oauthAuthorized"])
        self.assertEqual(state["oauthHealth"]["state"], "token_expired")
        self.assertEqual(analytics["state"], "attention")
        self.assertIn("renouveler", analytics["detail"])

    def test_authorization_url_uses_incremental_scopes_and_state(self):
        self.install_client()
        result = hub.create_authorization_url(
            "https://www.checkupauto.fr",
            ["analytics", "business_profile"],
        )
        parsed = urlparse(result["authorizationUrl"])
        params = parse_qs(parsed.query)
        scopes = set(params["scope"][0].split())
        self.assertIn("https://www.googleapis.com/auth/analytics.readonly", scopes)
        self.assertIn("https://www.googleapis.com/auth/business.manage", scopes)
        self.assertEqual(params["access_type"], ["offline"])
        self.assertEqual(params["include_granted_scopes"], ["true"])
        self.assertTrue(hub.STATE_FILE.exists())

    def test_callback_rejects_wrong_state(self):
        self.install_client()
        hub.create_authorization_url("https://www.checkupauto.fr", ["analytics"])
        with self.assertRaises(hub.IntegrationError):
            hub.handle_oauth_callback(
                "https://www.checkupauto.fr",
                "wrong-state",
                "code",
            )

    def test_callback_persists_token_and_marks_connector_connected(self):
        self.install_client()
        auth = hub.create_authorization_url("https://www.checkupauto.fr", ["analytics"])
        state = parse_qs(urlparse(auth["authorizationUrl"]).query)["state"][0]
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "access_token": "access",
            "refresh_token": "refresh",
            "expires_in": 3600,
            "scope": "https://www.googleapis.com/auth/analytics.readonly",
            "token_type": "Bearer",
        }
        with patch("integration_hub.requests.post", return_value=response):
            hub.handle_oauth_callback("https://www.checkupauto.fr", state, "code")
        status = hub.status()
        analytics = next(x for x in status["connectors"] if x["id"] == "analytics")
        self.assertTrue(analytics["connected"])
        saved = json.loads(hub.TOKEN_FILE.read_text())
        self.assertEqual(saved["refresh_token"], "refresh")
        self.assertIn("expires_at", saved)
        self.assertFalse(hub.STATE_FILE.exists())

    def test_ads_is_partial_until_developer_token_is_configured(self):
        self.install_client()
        hub._atomic_json(hub.TOKEN_FILE, {
            "refresh_token": "refresh",
            "scope": "https://www.googleapis.com/auth/adwords",
        })
        ads = next(x for x in hub.status()["connectors"] if x["id"] == "google_ads")
        self.assertFalse(ads["connected"])
        self.assertEqual(ads["state"], "attention")
        hub.save_settings({"googleAdsDeveloperToken": "dev-token"})
        ads = next(x for x in hub.status()["connectors"] if x["id"] == "google_ads")
        self.assertTrue(ads["connected"])

    def test_legacy_search_console_is_reported_connected(self):
        row = next(
            x for x in hub.status({"configured": True})["connectors"]
            if x["id"] == "search_console"
        )
        self.assertTrue(row["connected"])
        self.assertIn("compte de service", row["detail"].lower())

    def test_gmail_is_partial_until_sender_is_configured(self):
        self.install_client()
        hub._atomic_json(hub.TOKEN_FILE, {
            "refresh_token": "refresh",
            "scope": "https://www.googleapis.com/auth/gmail.send",
        })
        gmail = next(x for x in hub.status()["connectors"] if x["id"] == "gmail")
        self.assertFalse(gmail["connected"])
        self.assertEqual(gmail["state"], "attention")
        hub.save_settings({"gmailSender": "contact@checkupauto.fr"})
        gmail = next(x for x in hub.status()["connectors"] if x["id"] == "gmail")
        self.assertTrue(gmail["connected"])
        self.assertEqual(hub.settings_info()["gmailSender"], "contact@checkupauto.fr")

    def test_gmail_sender_must_be_valid_email(self):
        with self.assertRaisesRegex(hub.IntegrationError, "Gmail invalide"):
            hub.save_settings({"gmailSender": "not-an-email"})

    def test_refresh_token_flow(self):
        self.install_client()
        hub._atomic_json(hub.TOKEN_FILE, {
            "refresh_token": "refresh",
            "scope": "https://www.googleapis.com/auth/analytics.readonly",
        })
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"access_token": "new-access", "expires_in": 3600}
        with patch("integration_hub.requests.post", return_value=response) as post:
            token = hub.google_access_token(
                ["https://www.googleapis.com/auth/analytics.readonly"]
            )
        self.assertEqual(token, "new-access")
        self.assertEqual(post.call_args.kwargs["data"]["grant_type"], "refresh_token")

    def test_refresh_ignores_tampered_persisted_token_endpoint(self):
        self.install_client()
        client = json.loads(hub.CLIENT_FILE.read_text())
        client["token_uri"] = "https://attacker.invalid/token"
        hub._atomic_json(hub.CLIENT_FILE, client)
        hub._atomic_json(hub.TOKEN_FILE, {
            "refresh_token": "refresh",
            "scope": "https://www.googleapis.com/auth/analytics.readonly",
        })
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"access_token": "new-access", "expires_in": 3600}
        with patch("integration_hub.requests.post", return_value=response) as post:
            token = hub.google_access_token(["https://www.googleapis.com/auth/analytics.readonly"])
        self.assertEqual(token, "new-access")
        self.assertEqual(post.call_args.args[0], hub.TOKEN_URL)

    def test_refresh_503_preserves_retry_after(self):
        self.install_client()
        hub._atomic_json(hub.TOKEN_FILE, {
            "refresh_token": "refresh",
            "scope": "https://www.googleapis.com/auth/gmail.send",
        })
        response = Mock()
        response.status_code = 503
        response.headers = {"Retry-After": "90"}
        with patch("integration_hub.requests.post", return_value=response):
            with self.assertRaises(hub.IntegrationHTTPError) as caught:
                hub.google_access_token(["https://www.googleapis.com/auth/gmail.send"])
        self.assertEqual(caught.exception.status, 503)
        self.assertEqual(caught.exception.retry_after, "90")
        self.assertTrue(caught.exception.retryable)


    def test_force_refresh_does_not_trust_cached_access_token(self):
        self.install_client()
        hub._atomic_json(hub.TOKEN_FILE, {
            "access_token": "cached-access",
            "refresh_token": "refresh",
            "scope": "https://www.googleapis.com/auth/gmail.send",
            "expires_at": (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)).isoformat(),
        })
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"access_token": "validated-access", "expires_in": 3600}
        with patch("integration_hub.requests.post", return_value=response) as post:
            token = hub.google_access_token(
                ["https://www.googleapis.com/auth/gmail.send"], force_refresh=True
            )
        self.assertEqual(token, "validated-access")
        post.assert_called_once()


if __name__ == "__main__":
    unittest.main()
