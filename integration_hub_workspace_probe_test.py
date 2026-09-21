import datetime
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

import integration_hub


class _Response:
    def __init__(self, status_code=200, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.headers = headers or {}

    def json(self):
        return self._payload


class IntegrationHubWorkspaceProbeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        private = Path(self.tmp.name)
        integration_hub.PRIVATE_DIR = private
        integration_hub.INTEGRATION_DIR = private / "integrations"
        integration_hub.CLIENT_FILE = integration_hub.INTEGRATION_DIR / "google-oauth-client.json"
        integration_hub.TOKEN_FILE = integration_hub.INTEGRATION_DIR / "google-oauth-token.json"
        integration_hub.SETTINGS_FILE = integration_hub.INTEGRATION_DIR / "google-settings.json"
        integration_hub.STATE_FILE = integration_hub.INTEGRATION_DIR / "google-oauth-state.json"
        integration_hub.INTEGRATION_DIR.mkdir(parents=True)
        integration_hub.save_oauth_client({
            "web": {
                "client_id": "fake-client.apps.googleusercontent.com",
                "client_secret": "fake-secret",
                "redirect_uris": [
                    "https://www.checkupauto.fr/api/integrations/google/oauth/callback"
                ],
            }
        })
        now = datetime.datetime.now(datetime.timezone.utc)
        integration_hub.TOKEN_FILE.write_text(json.dumps({
            "access_token": "fake-access-token",
            "scope": " ".join([
                integration_hub.CALENDAR_SCOPE,
                integration_hub.DRIVE_SCOPE,
            ]),
            "expires_at": (now + datetime.timedelta(hours=1)).isoformat(),
        }))

    def tearDown(self):
        self.tmp.cleanup()

    def _rows(self, get_mock):
        with patch.object(integration_hub.requests, "get", side_effect=get_mock):
            payload = integration_hub.status(
                {},
                "https://www.checkupauto.fr",
                verify_remote=True,
            )
        return {row["id"]: row for row in payload["connectors"]}

    def test_calendar_probe_uses_bounded_read_only_endpoint(self):
        response = _Response(payload={"kind": "calendar#events", "items": []})
        with patch.object(integration_hub.requests, "get", return_value=response) as get:
            probe = integration_hub.calendar_events_probe()
        self.assertEqual({"connected": True, "verification": "verified"}, probe)
        get.assert_called_once_with(
            integration_hub.CALENDAR_EVENTS_URL,
            headers={"Authorization": "Bearer fake-access-token"},
            params={"maxResults": 1},
            timeout=20,
        )

    def test_drive_probe_uses_bounded_read_only_endpoint(self):
        response = _Response(payload={"kind": "drive#fileList", "files": []})
        with patch.object(integration_hub.requests, "get", return_value=response) as get:
            probe = integration_hub.drive_files_probe()
        self.assertEqual({"connected": True, "verification": "verified"}, probe)
        get.assert_called_once_with(
            integration_hub.DRIVE_FILES_URL,
            headers={"Authorization": "Bearer fake-access-token"},
            params={"pageSize": 1, "fields": "kind,files(id)"},
            timeout=20,
        )

    def test_status_verifies_calendar_and_drive(self):
        def route(url, **kwargs):
            if url == integration_hub.CALENDAR_EVENTS_URL:
                return _Response(payload={"kind": "calendar#events", "items": []})
            if url == integration_hub.DRIVE_FILES_URL:
                return _Response(payload={"kind": "drive#fileList", "files": []})
            self.fail(f"unexpected URL {url}")

        rows = self._rows(route)
        for connector in ("calendar", "drive"):
            self.assertTrue(rows[connector]["connected"])
            self.assertEqual("connected", rows[connector]["state"])
            self.assertEqual("verified", rows[connector]["verification"])

    def test_calendar_denial_cannot_remain_connected(self):
        def route(url, **kwargs):
            if url == integration_hub.CALENDAR_EVENTS_URL:
                return _Response(status_code=403)
            if url == integration_hub.DRIVE_FILES_URL:
                return _Response(payload={"kind": "drive#fileList", "files": []})
            self.fail(f"unexpected URL {url}")

        row = self._rows(route)["calendar"]
        self.assertFalse(row["connected"])
        self.assertEqual("attention", row["state"])
        self.assertEqual("failed", row["verification"])

    def test_drive_denial_cannot_remain_connected(self):
        def route(url, **kwargs):
            if url == integration_hub.CALENDAR_EVENTS_URL:
                return _Response(payload={"kind": "calendar#events", "items": []})
            if url == integration_hub.DRIVE_FILES_URL:
                return _Response(status_code=403)
            self.fail(f"unexpected URL {url}")

        row = self._rows(route)["drive"]
        self.assertFalse(row["connected"])
        self.assertEqual("attention", row["state"])
        self.assertEqual("failed", row["verification"])

    def test_calendar_network_failure_is_unavailable_without_exception_text(self):
        sensitive = "socket detail should not leak"

        def route(url, **kwargs):
            if url == integration_hub.CALENDAR_EVENTS_URL:
                raise requests.ConnectionError(sensitive)
            if url == integration_hub.DRIVE_FILES_URL:
                return _Response(payload={"kind": "drive#fileList", "files": []})
            self.fail(f"unexpected URL {url}")

        row = self._rows(route)["calendar"]
        self.assertFalse(row["connected"])
        self.assertEqual("unavailable", row["verification"])
        self.assertNotIn(sensitive, row["detail"])

    def test_drive_network_failure_is_unavailable_without_exception_text(self):
        sensitive = "socket detail should not leak"

        def route(url, **kwargs):
            if url == integration_hub.CALENDAR_EVENTS_URL:
                return _Response(payload={"kind": "calendar#events", "items": []})
            if url == integration_hub.DRIVE_FILES_URL:
                raise requests.ConnectionError(sensitive)
            self.fail(f"unexpected URL {url}")

        row = self._rows(route)["drive"]
        self.assertFalse(row["connected"])
        self.assertEqual("unavailable", row["verification"])
        self.assertNotIn(sensitive, row["detail"])

    def test_calendar_retry_after_is_bounded_and_retryable(self):
        response = _Response(
            status_code=503,
            headers={"Retry-After": "x" * 120},
        )
        with patch.object(integration_hub.requests, "get", return_value=response):
            with self.assertRaises(integration_hub.IntegrationHTTPError) as caught:
                integration_hub.calendar_events_probe()
        self.assertTrue(caught.exception.retryable)
        self.assertEqual(503, caught.exception.status)
        self.assertEqual("x" * 80, caught.exception.retry_after)

    def test_drive_retry_after_is_bounded_and_retryable(self):
        response = _Response(
            status_code=503,
            headers={"Retry-After": "y" * 120},
        )
        with patch.object(integration_hub.requests, "get", return_value=response):
            with self.assertRaises(integration_hub.IntegrationHTTPError) as caught:
                integration_hub.drive_files_probe()
        self.assertTrue(caught.exception.retryable)
        self.assertEqual(503, caught.exception.status)
        self.assertEqual("y" * 80, caught.exception.retry_after)

    def test_invalid_remote_schemas_are_rejected(self):
        with patch.object(
            integration_hub.requests,
            "get",
            return_value=_Response(payload={"kind": "calendar#events", "items": {}}),
        ):
            with self.assertRaises(integration_hub.IntegrationError):
                integration_hub.calendar_events_probe()
        with patch.object(
            integration_hub.requests,
            "get",
            return_value=_Response(payload={"kind": "drive#fileList", "files": {}}),
        ):
            with self.assertRaises(integration_hub.IntegrationError):
                integration_hub.drive_files_probe()


if __name__ == "__main__":
    unittest.main()
