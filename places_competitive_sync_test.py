import datetime
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

_IMPORT_DATA = tempfile.TemporaryDirectory()
_PREVIOUS_DATA_DIR = os.environ.get("CYBERCHECK_DATA_DIR")
os.environ["CYBERCHECK_DATA_DIR"] = _IMPORT_DATA.name
try:
    import places_competitive_sync as places
finally:
    if _PREVIOUS_DATA_DIR is None:
        os.environ.pop("CYBERCHECK_DATA_DIR", None)
    else:
        os.environ["CYBERCHECK_DATA_DIR"] = _PREVIOUS_DATA_DIR


class PlacesCompetitiveSyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = patch.dict("os.environ", {"CYBERCHECK_DATA_DIR": str(self.root)}, clear=False)
        self.env.start()
        self.now = datetime.datetime(2026, 9, 21, 18, 0, tzinfo=datetime.timezone.utc)
        self.catalog = {
            "center": {"label": "Checkup Auto Les Mureaux", "latitude": 48.98012, "longitude": 1.890251},
            "radiusKm": 50.01,
        }

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    @staticmethod
    def response(status=200, payload=None):
        response = Mock()
        response.status_code = status
        response.json.return_value = {} if payload is None else payload
        return response

    def test_missing_key_never_calls_google(self):
        with patch("places_competitive_sync.integration_hub.settings", return_value={}), \
             patch.dict("os.environ", {"GOOGLE_PLACES_API_KEY": ""}, clear=False), \
             patch("places_competitive_sync.requests.post") as post:
            result = places.sync_once(now=self.now)
        post.assert_not_called()
        self.assertEqual(result["state"], "not_configured")
        self.assertFalse(result["queried"])

    def test_success_is_bounded_and_never_returns_secret(self):
        payload = {
            "places": [{
                "id": "place-1",
                "displayName": {"text": "Centre Test"},
                "formattedAddress": "10 rue Test, 78130 Les Mureaux",
                "location": {"latitude": 48.981, "longitude": 1.891},
                "rating": 4.7,
                "userRatingCount": 123,
                "businessStatus": "OPERATIONAL",
                "googleMapsUri": "https://maps.google.com/?cid=test",
            }]
        }
        recorded = []
        with patch("places_competitive_sync.integration_hub.settings", return_value={"mapsApiKey": "secret-key"}), \
             patch("places_competitive_sync.geo_marketing.catalog", return_value=self.catalog), \
             patch("places_competitive_sync.requests.post", return_value=self.response(200, payload)) as post, \
             patch("places_competitive_sync._existing_competitor_id", return_value="known-centre"), \
             patch("places_competitive_sync.competitive.upsert_competitor") as upsert, \
             patch("places_competitive_sync.competitive.add_observation", side_effect=lambda *args, **kwargs: recorded.append((args, kwargs))):
            result = places.sync_once(force=True, now=self.now)

        self.assertTrue(result["ok"])
        self.assertEqual(result["state"], "verified")
        self.assertEqual(result["imported"], 1)
        self.assertNotIn("secret-key", str(result))
        post.assert_called_once()
        args, kwargs = post.call_args
        self.assertEqual(args[0], places.PLACES_SEARCH_URL)
        self.assertEqual(kwargs["timeout"], 20)
        self.assertEqual(kwargs["json"]["pageSize"], 20)
        self.assertEqual(kwargs["json"]["locationBias"]["circle"]["radius"], 50000.0)
        self.assertEqual(kwargs["headers"]["X-Goog-Api-Key"], "secret-key")
        self.assertEqual(kwargs["headers"]["X-Goog-FieldMask"], places.FIELD_MASK)
        upsert.assert_called_once()
        self.assertEqual(len(recorded), 2)
        self.assertEqual(recorded[0][0][2], "google_places_snapshot")
        self.assertEqual(recorded[1][0][2], "reviews_summary")

    def test_success_cadence_prevents_hourly_billable_calls(self):
        places._write_state({
            "schemaVersion": 1,
            "lastAttemptAt": "2026-09-21T17:00:00+00:00",
            "lastSuccessAt": "2026-09-21T17:00:00+00:00",
            "verification": "verified",
            "imported": 4,
        })
        with patch("places_competitive_sync.integration_hub.settings", return_value={"mapsApiKey": "secret-key"}), \
             patch("places_competitive_sync.requests.post") as post:
            result = places.sync_once(now=self.now)
        post.assert_not_called()
        self.assertEqual(result["state"], "not_due")
        self.assertFalse(result["queried"])

    def test_failed_attempt_uses_six_hour_retry_window(self):
        places._write_state({
            "schemaVersion": 1,
            "lastAttemptAt": "2026-09-21T17:00:00+00:00",
            "verification": "failed",
            "imported": 0,
        })
        with patch("places_competitive_sync.integration_hub.settings", return_value={"mapsApiKey": "secret-key"}), \
             patch("places_competitive_sync.requests.post") as post:
            result = places.sync_once(now=self.now)
        post.assert_not_called()
        self.assertEqual(result["state"], "not_due")

    def test_network_error_is_sanitized_and_recorded_unavailable(self):
        with patch("places_competitive_sync.integration_hub.settings", return_value={"mapsApiKey": "secret-key"}), \
             patch("places_competitive_sync.geo_marketing.catalog", return_value=self.catalog), \
             patch("places_competitive_sync.requests.post", side_effect=requests.RequestException("contains-sensitive-detail")):
            result = places.sync_once(force=True, now=self.now)
        self.assertEqual(result["state"], "unavailable")
        self.assertNotIn("contains-sensitive-detail", str(result))
        self.assertNotIn("secret-key", str(result))
        self.assertEqual(places._read_state()["verification"], "unavailable")

    def test_http_error_does_not_expose_google_response_body(self):
        response = self.response(403, {"error": {"message": "sensitive provider detail"}})
        response.text = "sensitive provider detail"
        with patch("places_competitive_sync.integration_hub.settings", return_value={"mapsApiKey": "secret-key"}), \
             patch("places_competitive_sync.geo_marketing.catalog", return_value=self.catalog), \
             patch("places_competitive_sync.requests.post", return_value=response):
            result = places.sync_once(force=True, now=self.now)
        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["httpStatus"], 403)
        self.assertNotIn("sensitive provider detail", str(result))
        self.assertNotIn("secret-key", str(result))

    def test_out_of_radius_place_is_not_imported(self):
        payload = {
            "places": [{
                "id": "far-away",
                "displayName": {"text": "Centre Lointain"},
                "formattedAddress": "Loin",
                "location": {"latitude": 50.0, "longitude": 3.0},
                "rating": 5.0,
                "userRatingCount": 5,
            }]
        }
        with patch("places_competitive_sync.integration_hub.settings", return_value={"mapsApiKey": "secret-key"}), \
             patch("places_competitive_sync.geo_marketing.catalog", return_value=self.catalog), \
             patch("places_competitive_sync.requests.post", return_value=self.response(200, payload)), \
             patch("places_competitive_sync.competitive.upsert_competitor") as upsert, \
             patch("places_competitive_sync.competitive.add_observation") as add:
            result = places.sync_once(force=True, now=self.now)
        self.assertEqual(result["imported"], 0)
        upsert.assert_not_called()
        add.assert_not_called()


if __name__ == "__main__":
    unittest.main()
