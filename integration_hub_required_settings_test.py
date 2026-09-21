import datetime
import tempfile
import unittest
from pathlib import Path

import integration_hub as hub


class IntegrationHubRequiredSettingsTest(unittest.TestCase):
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

    def tearDown(self):
        self.tmp.cleanup()

    def _authorize(self, scope):
        hub._atomic_json(hub.TOKEN_FILE, {
            "access_token": "test-access",
            "refresh_token": "test-refresh",
            "scope": scope,
            "expires_at": (
                datetime.datetime.now(datetime.timezone.utc)
                + datetime.timedelta(hours=1)
            ).isoformat(),
        })

    def _connector(self, connector_id):
        return next(
            row for row in hub.status()["connectors"]
            if row["id"] == connector_id
        )

    def test_analytics_requires_property_id(self):
        self._authorize("https://www.googleapis.com/auth/analytics.readonly")
        row = self._connector("analytics")
        self.assertFalse(row["connected"])
        self.assertEqual(row["state"], "attention")
        hub.save_settings({"analyticsPropertyId": "123456789"})
        self.assertTrue(self._connector("analytics")["connected"])

    def test_business_profile_requires_account_id(self):
        self._authorize("https://www.googleapis.com/auth/business.manage")
        row = self._connector("business_profile")
        self.assertFalse(row["connected"])
        self.assertEqual(row["state"], "attention")
        hub.save_settings({"businessAccountId": "accounts/123456"})
        self.assertTrue(self._connector("business_profile")["connected"])

    def test_tag_manager_requires_account_id(self):
        self._authorize("https://www.googleapis.com/auth/tagmanager.readonly")
        row = self._connector("tag_manager")
        self.assertFalse(row["connected"])
        self.assertEqual(row["state"], "attention")
        hub.save_settings({"tagManagerAccountId": "accounts/654321"})
        self.assertTrue(self._connector("tag_manager")["connected"])


if __name__ == "__main__":
    unittest.main()
