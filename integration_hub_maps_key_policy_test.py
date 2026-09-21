import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import integration_hub as hub


class IntegrationHubMapsKeyPolicyTest(unittest.TestCase):
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
    def _maps_row(state):
        return next(row for row in state["connectors"] if row["id"] == "maps_places")

    def test_missing_key_remains_available(self):
        row = self._maps_row(hub.status({}, "https://www.checkupauto.fr"))
        self.assertFalse(row["connected"])
        self.assertEqual(row["state"], "available")
        self.assertEqual(row["detail"], "Clé API requise")

    def test_configured_key_is_not_claimed_as_remotely_connected(self):
        hub.save_settings({"mapsApiKey": "test-maps-api-key"})
        row = self._maps_row(hub.status({}, "https://www.checkupauto.fr"))
        self.assertFalse(row["connected"])
        self.assertEqual(row["state"], "attention")
        self.assertEqual(row["verification"], "unverified")
        self.assertIn("vérification distante non exécutée", row["detail"])
        self.assertNotIn("test-maps-api-key", str(row))

    def test_status_does_not_spend_a_maps_api_request_for_readiness(self):
        hub.save_settings({"mapsApiKey": "test-maps-api-key"})
        with patch("integration_hub.requests.get") as get:
            row = self._maps_row(hub.status({}, "https://www.checkupauto.fr"))
        get.assert_not_called()
        self.assertEqual(row["verification"], "unverified")

    def test_settings_info_exposes_only_key_presence(self):
        hub.save_settings({"mapsApiKey": "test-maps-api-key"})
        info = hub.settings_info()
        self.assertTrue(info["mapsApiKeyConfigured"])
        self.assertNotIn("test-maps-api-key", str(info))


if __name__ == "__main__":
    unittest.main()
