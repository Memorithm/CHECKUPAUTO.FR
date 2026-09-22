from __future__ import annotations

import http.client
import importlib
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock


class AdminProcessingReviewAPITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private = tempfile.TemporaryDirectory()
        Path(cls.private.name, "admin-password").write_text("test-password\n", encoding="utf-8")
        cls.previous = {
            name: os.environ.get(name)
            for name in ("CYBERCHECK_PRIVATE_DIR", "CYBERCHECK_DATA_DIR", "CYBERCHECK_SECURITY_DIR")
        }
        os.environ["CYBERCHECK_PRIVATE_DIR"] = cls.private.name
        os.environ["CYBERCHECK_DATA_DIR"] = cls.private.name
        os.environ["CYBERCHECK_SECURITY_DIR"] = str(Path(cls.private.name, "security"))
        cls.admin_server = importlib.import_module("admin_server")

    @classmethod
    def tearDownClass(cls):
        for name, previous in cls.previous.items():
            if previous is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = previous
        cls.private.cleanup()

    def _post(self, payload, *, adapter_status=201, adapter_body=None, mfa=False):
        admin_server = self.admin_server
        calls = []

        def review(value):
            calls.append(value)
            return adapter_status, adapter_body or {
                "ok": True,
                "review": {
                    "activityId": "activity-1",
                    "currentActivityHash": "a" * 64,
                    "reviewedActivityHash": "a" * 64,
                    "securityStatus": "approved",
                    "privacyStatus": "approved",
                    "stale": False,
                },
            }

        with (
            mock.patch.object(admin_server.Handler, "_guard", return_value=True),
            mock.patch.object(admin_server.Handler, "authorized", return_value=True),
            mock.patch.object(admin_server.Handler, "_admin_origin_ok", return_value=True),
            mock.patch.object(admin_server.Handler, "_mfa_session_valid", return_value=not mfa),
            mock.patch.object(admin_server.admin_mfa, "configured", return_value=mfa),
            mock.patch.object(admin_server.compliance_admin_http, "review_high_risk_processing", side_effect=review),
        ):
            server = admin_server.ThreadingHTTPServer(("127.0.0.1", 0), admin_server.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                body = json.dumps(payload).encode("utf-8")
                connection = http.client.HTTPConnection(*server.server_address, timeout=5)
                connection.request(
                    "POST",
                    "/api/admin/compliance/processing-review",
                    body=body,
                    headers={"Content-Type": "application/json"},
                )
                response = connection.getresponse()
                data = json.loads(response.read().decode("utf-8"))
                connection.close()
                return response.status, data, calls
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_payload_reaches_sanitized_adapter_unchanged(self):
        payload = {
            "activityId": "activity-1",
            "expectedActivityHash": "a" * 64,
            "securityStatus": "approved",
            "privacyStatus": "approved",
            "evidence": "review record kept outside the HTTP response",
        }
        status, data, calls = self._post(payload)
        self.assertEqual(status, 201)
        self.assertTrue(data["ok"])
        self.assertEqual(calls, [payload])
        self.assertNotIn("evidence", json.dumps(data))

    def test_stale_digest_conflict_from_adapter_is_preserved(self):
        body = {"ok": False, "error": "compliance_processing_review_conflict"}
        status, data, calls = self._post({"activityId": "activity-1"}, adapter_status=409, adapter_body=body)
        self.assertEqual(status, 409)
        self.assertEqual(data, body)
        self.assertEqual(calls, [{"activityId": "activity-1"}])

    def test_internal_error_remains_sanitized(self):
        body = {"ok": False, "error": "compliance_processing_review_failed"}
        status, data, _ = self._post(
            {"activityId": "activity-1", "evidence": "secret-review-marker"},
            adapter_status=500,
            adapter_body=body,
        )
        self.assertEqual(status, 500)
        self.assertEqual(data, body)
        self.assertNotIn("secret-review-marker", json.dumps(data))

    def test_mfa_gate_runs_before_processing_review(self):
        payload = {
            "activityId": "activity-1",
            "expectedActivityHash": "a" * 64,
            "securityStatus": "approved",
            "privacyStatus": "approved",
            "evidence": "review",
        }
        status, data, calls = self._post(payload, mfa=True)
        self.assertEqual(status, 403)
        self.assertEqual(data, {"ok": False, "error": "two_factor_required"})
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
