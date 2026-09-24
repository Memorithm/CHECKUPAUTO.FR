import io
import json
import unittest
from unittest import mock
from urllib import error

import passenger_wsgi
import public_surface_provenance as provenance


SHA = "0123456789abcdef0123456789abcdef01234567"
OTHER_SHA = "89abcdef0123456789abcdef0123456789abcdef"


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


def _payload(**overrides):
    payload = {
        "schemaVersion": 1,
        "surface": "checkupauto-cybercheck",
        "purpose": "public-deployment-provenance",
        "verified": True,
        "state": "verified",
        "gitSha": SHA,
        "branch": "main",
        "clean": True,
    }
    payload.update(overrides)
    return json.dumps(payload).encode("utf-8")


class PublicDeploymentProvenanceTest(unittest.TestCase):
    def test_runtime_evidence_is_minimal_and_requires_clean_main_checkout(self):
        state = {
            "available": True,
            "head": SHA,
            "branch": "main",
            "dirty": False,
            "changedTracked": ["secret.txt"],
            "error": "must-not-leak",
        }
        result = provenance.runtime_evidence(state)
        self.assertEqual(result, {
            "schemaVersion": 1,
            "surface": "checkupauto-cybercheck",
            "purpose": "public-deployment-provenance",
            "verified": True,
            "state": "verified",
            "gitSha": SHA,
            "branch": "main",
            "clean": True,
        })
        self.assertNotIn("changedTracked", result)
        self.assertNotIn("error", result)

        self.assertFalse(provenance.runtime_evidence({**state, "dirty": True})["verified"])
        self.assertEqual(provenance.runtime_evidence({**state, "dirty": True})["state"], "dirty_worktree")
        self.assertEqual(provenance.runtime_evidence({**state, "branch": "feature"})["state"], "wrong_branch")
        self.assertEqual(provenance.runtime_evidence({**state, "head": "short"})["state"], "invalid_git_sha")
        self.assertEqual(provenance.runtime_evidence({"available": False})["state"], "git_unavailable")

    def test_deployment_probe_requires_exact_expected_sha_main_and_clean(self):
        opener = _Opener(_Response(_payload()))
        result = provenance.probe_deployment("https://www.checkupauto.fr/", SHA, opener=opener, timeout=1.25)
        self.assertEqual(result, {
            "ok": True,
            "state": "verified",
            "surface": "checkupauto-cybercheck",
            "provenancePath": "/api/public/deployment-provenance",
            "gitSha": SHA,
            "branch": "main",
            "clean": True,
        })
        self.assertEqual(opener.request.full_url, "https://www.checkupauto.fr/api/public/deployment-provenance")
        self.assertEqual(opener.timeout, 1.25)

        mismatch = provenance.probe_deployment(
            "https://www.checkupauto.fr/", OTHER_SHA, opener=_Opener(_Response(_payload()))
        )
        self.assertEqual(mismatch["state"], "deployment_sha_mismatch")
        self.assertFalse(mismatch["ok"])
        self.assertEqual(mismatch["gitSha"], "")

        dirty = provenance.probe_deployment(
            "https://www.checkupauto.fr/", SHA, opener=_Opener(_Response(_payload(verified=False, state="dirty_worktree", clean=False)))
        )
        self.assertEqual(dirty["state"], "runtime_not_clean")
        self.assertFalse(dirty["ok"])

    def test_deployment_probe_is_fail_closed_for_invalid_or_redirected_evidence(self):
        self.assertEqual(provenance.probe_deployment("https://www.checkupauto.fr/", "bad")["state"], "expected_sha_invalid")
        redirected = error.HTTPError(
            "https://www.checkupauto.fr/api/public/deployment-provenance",
            302,
            "Found",
            {"Location": "https://rdv.checkupauto.fr/"},
            None,
        )
        result = provenance.probe_deployment(
            "https://www.checkupauto.fr/", SHA, opener=_Opener(exc=redirected)
        )
        self.assertEqual(result["state"], "redirected")
        self.assertFalse(result["ok"])

        cases = (
            (_payload(branch="feature"), "wrong_branch"),
            (_payload(gitSha="short"), "invalid_provenance"),
            (_payload(surface="other"), "surface_mismatch"),
            (_payload(purpose="wrong"), "invalid_provenance"),
        )
        for payload, expected in cases:
            with self.subTest(expected=expected):
                result = provenance.probe_deployment(
                    "https://www.checkupauto.fr/", SHA, opener=_Opener(_Response(payload))
                )
                self.assertEqual(result["state"], expected)
                self.assertFalse(result["ok"])

    def test_wsgi_endpoint_returns_only_minimal_runtime_evidence_without_starting_backend(self):
        state = {"available": True, "head": SHA, "branch": "main", "dirty": False, "changedTracked": ["private"]}
        captured = {}

        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = dict(headers)

        with mock.patch.object(passenger_wsgi, "_runtime_git_state", return_value=state), \
             mock.patch.object(passenger_wsgi, "_PROVENANCE_CACHE", (0.0, b"")):
            body = b"".join(passenger_wsgi.application({
                "REQUEST_METHOD": "GET",
                "PATH_INFO": provenance.DEPLOYMENT_PROVENANCE_PATH,
            }, start_response))

        self.assertEqual(captured["status"], "200 OK")
        self.assertEqual(captured["headers"]["Cache-Control"], "no-store")
        payload = json.loads(body)
        self.assertTrue(payload["verified"])
        self.assertEqual(payload["gitSha"], SHA)
        self.assertEqual(set(payload), {"schemaVersion", "surface", "purpose", "verified", "state", "gitSha", "branch", "clean"})


if __name__ == "__main__":
    unittest.main()
