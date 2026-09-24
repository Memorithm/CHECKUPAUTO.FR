import ast
import io
import json
import pathlib
import unittest
from urllib import error

import public_surface_provenance as provenance


ROOT = pathlib.Path(__file__).resolve().parent


class _Headers(dict):
    def get(self, key, default=None):
        return super().get(key, default)


class _Response:
    def __init__(self, payload, *, status=200, content_type="application/json"):
        self.status = status
        self.headers = _Headers({"Content-Type": content_type})
        self._stream = io.BytesIO(payload)
        self.closed = False

    def getcode(self):
        return self.status

    def read(self, size=-1):
        return self._stream.read(size)

    def close(self):
        self.closed = True


class _Opener:
    def __init__(self, response=None, exc=None):
        self.response = response
        self.exc = exc
        self.request = None
        self.timeout = None

    def open(self, req, timeout=None):
        self.request = req
        self.timeout = timeout
        if self.exc is not None:
            raise self.exc
        return self.response


def _marker(**overrides):
    payload = {
        "schemaVersion": 1,
        "surface": "checkupauto-cybercheck",
        "purpose": "public-routing-provenance",
    }
    payload.update(overrides)
    return json.dumps(payload).encode("utf-8")


def _public_asset_suffixes():
    module = ast.parse((ROOT / "security_guard.py").read_text(encoding="utf-8"))
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == "_ASSET_SUFFIXES" for target in node.targets):
            value = ast.literal_eval(node.value)
            if isinstance(value, set):
                return value
    raise AssertionError("_ASSET_SUFFIXES not found")


class PublicSurfaceProvenanceTest(unittest.TestCase):
    def test_marker_asset_matches_probe_contract_and_static_policy(self):
        payload = json.loads((ROOT / "assets" / "cybercheck-runtime-marker.bin").read_text(encoding="utf-8"))
        self.assertEqual(payload["schemaVersion"], provenance.EXPECTED_SCHEMA_VERSION)
        self.assertEqual(payload["surface"], provenance.EXPECTED_SURFACE)
        self.assertEqual(payload["purpose"], "public-routing-provenance")
        self.assertEqual(provenance.MARKER_PATH, "/assets/cybercheck-runtime-marker.bin")
        suffixes = _public_asset_suffixes()
        self.assertIn(pathlib.Path(provenance.MARKER_PATH).suffix, suffixes)
        self.assertNotIn(".json", suffixes)

    def test_marker_url_is_strictly_bound_to_public_https_host(self):
        self.assertEqual(
            provenance.marker_url("https://www.checkupauto.fr/anything?ignored=yes"),
            "https://www.checkupauto.fr/assets/cybercheck-runtime-marker.bin",
        )
        for value in (
            "http://www.checkupauto.fr/",
            "https://rdv.checkupauto.fr/",
            "https://user:pass@www.checkupauto.fr/",
            "https://www.checkupauto.fr:444/",
            "",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                provenance.marker_url(value)

    def test_valid_marker_verifies_surface_without_returning_response_body(self):
        response = _Response(_marker(), content_type="application/octet-stream")
        opener = _Opener(response)
        result = provenance.probe("https://www.checkupauto.fr/", opener=opener, timeout=1.5)
        self.assertEqual(result, {
            "ok": True,
            "state": "verified",
            "surface": "checkupauto-cybercheck",
            "markerPath": "/assets/cybercheck-runtime-marker.bin",
        })
        self.assertEqual(opener.timeout, 1.5)
        self.assertEqual(opener.request.full_url, "https://www.checkupauto.fr/assets/cybercheck-runtime-marker.bin")
        self.assertTrue(response.closed)
        self.assertNotIn("payload", result)

    def test_json_content_type_remains_accepted_for_reverse_proxy_overrides(self):
        result = provenance.probe(
            "https://www.checkupauto.fr/",
            opener=_Opener(_Response(_marker(), content_type="application/json; charset=utf-8")),
        )
        self.assertTrue(result["ok"])

    def test_redirect_is_fail_closed(self):
        exc = error.HTTPError(
            "https://www.checkupauto.fr/assets/cybercheck-runtime-marker.bin",
            302,
            "Found",
            {"Location": "https://rdv.checkupauto.fr/"},
            None,
        )
        result = provenance.probe("https://www.checkupauto.fr/", opener=_Opener(exc=exc))
        self.assertEqual(result["state"], "redirected")
        self.assertFalse(result["ok"])
        self.assertEqual(result["surface"], "")

    def test_missing_marker_and_transport_failure_are_distinct_but_fail_closed(self):
        missing = error.HTTPError(
            "https://www.checkupauto.fr/assets/cybercheck-runtime-marker.bin",
            404,
            "Not Found",
            {},
            None,
        )
        self.assertEqual(
            provenance.probe("https://www.checkupauto.fr/", opener=_Opener(exc=missing))["state"],
            "marker_not_found",
        )
        unavailable = error.URLError("offline")
        self.assertEqual(
            provenance.probe("https://www.checkupauto.fr/", opener=_Opener(exc=unavailable))["state"],
            "unavailable",
        )

    def test_wrong_surface_invalid_content_and_oversize_never_verify(self):
        cases = (
            (_Response(_marker(surface="historical-site"), content_type="application/octet-stream"), "surface_mismatch"),
            (_Response(_marker(schemaVersion=2), content_type="application/octet-stream"), "invalid_marker"),
            (_Response(b"not-json", content_type="application/octet-stream"), "invalid_marker"),
            (_Response(_marker(), content_type="text/html"), "invalid_content_type"),
            (_Response(b"{" + b"x" * 5000 + b"}", content_type="application/octet-stream"), "response_too_large"),
        )
        for response, expected in cases:
            with self.subTest(expected=expected):
                result = provenance.probe("https://www.checkupauto.fr/", opener=_Opener(response))
                self.assertEqual(result["state"], expected)
                self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
