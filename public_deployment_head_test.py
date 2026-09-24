import unittest
from unittest import mock

import passenger_wsgi
import public_surface_provenance as provenance


SHA = "0123456789abcdef0123456789abcdef01234567"


class PublicDeploymentHeadTest(unittest.TestCase):
    def test_head_returns_headers_without_body_or_backend_start(self):
        captured = {}

        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = dict(headers)

        state = {"available": True, "head": SHA, "branch": "main", "dirty": False}
        with mock.patch.object(passenger_wsgi, "_runtime_git_state", return_value=state), \
             mock.patch.object(passenger_wsgi, "_PROVENANCE_CACHE", (0.0, b"")), \
             mock.patch.object(passenger_wsgi, "_ensure_backend", side_effect=AssertionError("backend must not start")):
            body = b"".join(passenger_wsgi.application({
                "REQUEST_METHOD": "HEAD",
                "PATH_INFO": provenance.DEPLOYMENT_PROVENANCE_PATH,
            }, start_response))

        self.assertEqual(captured["status"], "200 OK")
        self.assertEqual(body, b"")
        self.assertEqual(captured["headers"]["Cache-Control"], "no-store")
        self.assertEqual(captured["headers"]["X-Content-Type-Options"], "nosniff")
        self.assertGreater(int(captured["headers"]["Content-Length"]), 0)


if __name__ == "__main__":
    unittest.main()
