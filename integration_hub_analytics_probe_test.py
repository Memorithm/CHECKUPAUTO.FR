import datetime
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import integration_hub as hub


class IntegrationHubAnalyticsProbeTest(unittest.TestCase):
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
            "scope": hub.ANALYTICS_SCOPE,
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
    def _metadata(property_id="123456789"):
        return {
            "name": f"properties/{property_id}/metadata",
            "dimensions": [{"apiName": "country"}],
            "metrics": [{"apiName": "activeUsers"}],
        }

    def test_property_id_must_be_numeric_and_property_specific(self):
        for invalid in ("properties/123", "G-ABC123", "0", "１２３"):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(hub.IntegrationError, "propriété Google Analytics invalide"):
                    hub.save_settings({"analyticsPropertyId": invalid})

    def test_metadata_probe_uses_read_only_property_endpoint(self):
        hub.save_settings({"analyticsPropertyId": "123456789"})
        response = self._response(payload=self._metadata())
        with patch("integration_hub.requests.get", return_value=response) as get:
            result = hub.analytics_property_probe()
        self.assertTrue(result["connected"])
        self.assertEqual(result["verification"], "verified")
        self.assertEqual(result["dimensionCount"], 1)
        self.assertEqual(result["metricCount"], 1)
        get.assert_called_once_with(
            "https://analyticsdata.googleapis.com/v1beta/properties/123456789/metadata",
            headers={"Authorization": "Bearer test-access"},
            timeout=20,
        )
        self.assertNotIn("test-access", str(result))

    def test_admin_status_marks_analytics_verified_only_after_api_success(self):
        hub.save_settings({"analyticsPropertyId": "123456789"})
        with patch(
            "integration_hub.requests.get",
            return_value=self._response(payload=self._metadata()),
        ):
            state = hub.status({}, "https://www.checkupauto.fr")
        row = next(item for item in state["connectors"] if item["id"] == "analytics")
        self.assertTrue(row["connected"])
        self.assertEqual(row["verification"], "verified")
        self.assertEqual(row["detail"], "API Google Analytics vérifiée")
        self.assertEqual(row["probe"], {"dimensionCount": 1, "metricCount": 1})

    def test_denied_property_cannot_remain_connected(self):
        hub.save_settings({"analyticsPropertyId": "123456789"})
        with patch(
            "integration_hub.requests.get",
            return_value=self._response(status=403),
        ):
            state = hub.status({}, "https://www.checkupauto.fr")
        row = next(item for item in state["connectors"] if item["id"] == "analytics")
        self.assertFalse(row["connected"])
        self.assertEqual(row["state"], "attention")
        self.assertEqual(row["verification"], "failed")
        self.assertIn("propriété non accessible", row["detail"])

    def test_transient_google_failure_is_reported_unavailable_without_leaking_error(self):
        hub.save_settings({"analyticsPropertyId": "123456789"})
        with patch(
            "integration_hub.requests.get",
            side_effect=hub.requests.ConnectionError("token=do-not-expose"),
        ):
            state = hub.status({}, "https://www.checkupauto.fr")
        row = next(item for item in state["connectors"] if item["id"] == "analytics")
        self.assertFalse(row["connected"])
        self.assertEqual(row["verification"], "unavailable")
        self.assertNotIn("do-not-expose", row["detail"])

    def test_retryable_google_status_preserves_bounded_retry_after(self):
        hub.save_settings({"analyticsPropertyId": "123456789"})
        response = self._response(status=503, headers={"Retry-After": "60"})
        with patch("integration_hub.requests.get", return_value=response):
            with self.assertRaises(hub.IntegrationHTTPError) as caught:
                hub.analytics_property_probe()
        self.assertEqual(caught.exception.status, 503)
        self.assertEqual(caught.exception.retry_after, "60")
        self.assertTrue(caught.exception.retryable)


if __name__ == "__main__":
    unittest.main()
