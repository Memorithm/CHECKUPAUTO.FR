import os
import unittest
from unittest.mock import patch

import competitive_intelligence as competitive


class CompetitivePlacesConfigurationTest(unittest.TestCase):
    def test_integration_hub_maps_key_marks_places_configured(self):
        with patch("integration_hub.settings_info", return_value={"mapsApiKeyConfigured": True}), \
             patch.dict(os.environ, {"GOOGLE_PLACES_API_KEY": ""}, clear=False):
            status = competitive.connector_status()
        self.assertTrue(status["googlePlacesConfigured"])

    def test_legacy_environment_key_remains_supported(self):
        with patch("integration_hub.settings_info", return_value={"mapsApiKeyConfigured": False}), \
             patch.dict(os.environ, {"GOOGLE_PLACES_API_KEY": "legacy-secret"}, clear=False):
            status = competitive.connector_status()
        self.assertTrue(status["googlePlacesConfigured"])
        self.assertNotIn("legacy-secret", str(status))

    def test_missing_key_is_not_configured(self):
        with patch("integration_hub.settings_info", return_value={"mapsApiKeyConfigured": False}), \
             patch.dict(os.environ, {"GOOGLE_PLACES_API_KEY": ""}, clear=False):
            status = competitive.connector_status()
        self.assertFalse(status["googlePlacesConfigured"])


if __name__ == "__main__":
    unittest.main()
