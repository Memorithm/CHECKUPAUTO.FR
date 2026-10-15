"""FastLane public-config tests: conservative cache, no auth/session or stale data."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import public_config_fastlane as fastlane
import passenger_wsgi


class FastLaneConfigTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.private = Path(self.folder.name)
        self.default = self.private / "default.json"
        self.runtime = self.private / "runtime.json"
        self.default.write_text('{"version":1,"business":{"phone":"01 00 00 00 00"}}')
        self.reset = mock.patch.object(fastlane, "_ENTRY", None)
        self.reset.start()
        self.addCleanup(self.reset.stop)
        self.sr = mock.patch.object(fastlane.site_config_store, "runtime_config_path",
                                    return_value=self.runtime)
        self.sr.start()
        self.addCleanup(self.sr.stop)
        self.dc = mock.patch.object(fastlane.site_config_store, "DEFAULT_CONFIG", self.default)
        self.dc.start()
        self.addCleanup(self.dc.stop)

    def request(self, data=None):
        environ = {"REQUEST_METHOD": "GET", "PATH_INFO": "/api/site-config"}
        environ.update(data or {})
        response = {}
        def start(status, headers):
            response["status"], response["headers"] = status, dict(headers)
        body = fastlane.handle(environ, start)
        return response, b"".join(body) if body is not None else None

    def test_anonymous_get_hits_and_never_adds_a_browser_cache(self):
        (first, body), (second, cached) = self.request(), self.request()
        self.assertEqual(first["status"], "200 OK")
        self.assertEqual(first["headers"]["X-CheckupAuto-FastLane"], "miss")
        self.assertEqual(second["headers"]["X-CheckupAuto-FastLane"], "hit")
        self.assertEqual(first["headers"]["Cache-Control"], "no-store")
        self.assertEqual(first["headers"]["Content-Length"], str(len(body)))
        self.assertIn("fastlane;dur=", first["headers"]["Server-Timing"])
        self.assertEqual(body, cached)
        self.assertEqual(json.loads(body)["business"]["phone"], "01 00 00 00 00")

    def test_new_runtime_config_precedes_default_and_replacing_invalidates(self):
        (_, old) = self.request()
        self.runtime.write_text('{"version":2,"business":{"phone":"01 00 00 00 00"}}')
        (fresh, second) = self.request()
        self.assertEqual(fresh["headers"]["X-CheckupAuto-FastLane"], "miss")
        self.assertNotEqual(old, second)
        replacement = self.private / "replacement.json"
        replacement.write_text('{"version":3,"business":{"phone":"01 00 00 00 00"}}')
        os.replace(replacement, self.runtime)
        (latest, third) = self.request()
        self.assertEqual(latest["headers"]["X-CheckupAuto-FastLane"], "miss")
        self.assertEqual(json.loads(third)["version"], 3)
        self.assertEqual(self.request()[0]["headers"]["X-CheckupAuto-FastLane"], "hit")

    def test_corrupt_or_removed_config_fails_closed_without_stale_cache(self):
        self.runtime.write_text('{"version":2}')
        self.assertEqual(self.request()[0]["status"], "200 OK")
        self.runtime.write_text("{ invalid")
        (bad, payload) = self.request()
        self.assertEqual(bad["status"], "503 Service Unavailable")
        self.assertEqual(bad["headers"]["Cache-Control"], "no-store")
        self.assertEqual(json.loads(payload)["error"], "public_config_unavailable")
        self.assertNotIn(str(self.private), payload.decode())

    def test_bounded_size(self):
        self.runtime.write_text(json.dumps({"x": "a" * (fastlane.MAX_BYTES + 1)}))
        self.assertEqual(self.request()[0]["status"], "503 Service Unavailable")

    def test_sensitive_or_ambiguous_requests_are_not_intercepted(self):
        for request in (
            {"REQUEST_METHOD": "POST"},
            {"REQUEST_METHOD": "HEAD"},
            {"PATH_INFO": "/api/customer/me"},
            {"PATH_INFO": "/api/booking/availability"},
            {"PATH_INFO": "/compte"},
            {"PATH_INFO": "/payment/payline/checkout"},
            {"QUERY_STRING": "debug=1"},
            {"HTTP_COOKIE": "CyberCheckSession=private"},
            {"HTTP_AUTHORIZATION": "Basic secret"},
            {"CONTENT_LENGTH": "1"},
            {"HTTP_TRANSFER_ENCODING": "chunked"},
        ):
            with self.subTest(request=request):
                self.assertEqual(self.request(request), ({}, None))

    def test_wsgi_serves_public_get_without_initializing_backend(self):
        environ = {"REQUEST_METHOD": "GET", "PATH_INFO": "/api/site-config"}
        emitted = []
        with mock.patch.object(passenger_wsgi, "_ensure_backend",
                               side_effect=AssertionError("backend cold start forbidden")), \
             mock.patch.object(passenger_wsgi.migration_write_freeze, "status",
                               return_value={"active": False}):
            response = passenger_wsgi.application(
                environ, lambda status, headers: emitted.append((status, dict(headers))))
        self.assertEqual(emitted[0][0], "200 OK")
        self.assertEqual(emitted[0][1]["Cache-Control"], "no-store")
        self.assertEqual(json.loads(b"".join(response))["version"], 1)

    def test_public_hero_preload_matches_rendered_responsive_image(self):
        html = (Path(__file__).parent / "index.html").read_text(encoding="utf-8")
        self.assertEqual(html.count('rel="preload" as="image"'), 1)
        self.assertIn('imagesizes="(max-width: 980px) 92vw, (min-width: 1600px) 900px, 56vw"',html)
        self.assertIn('sizes="(max-width: 980px) 92vw, (min-width: 1600px) 900px, 56vw"',html)
        self.assertIn("checkupauto-lavis-option2-1020.webp", html)
        self.assertIn('fetchpriority="high"', html)
        self.assertNotIn('CyberCheckVehicle_Photo3D.glb', html)


if __name__ == "__main__":
    unittest.main()
