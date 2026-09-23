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


class AdminComplianceRegistersAPITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private = tempfile.TemporaryDirectory()
        Path(cls.private.name, "admin-password").write_text("test-password\n", encoding="utf-8")
        cls.previous = {name: os.environ.get(name) for name in ("CYBERCHECK_PRIVATE_DIR", "CYBERCHECK_DATA_DIR", "CYBERCHECK_SECURITY_DIR")}
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

    def _post(self, path, payload, *, activity_error=None, processor_error=None, mfa=False, origin_ok=True, content_type="application/json"):
        admin_server = self.admin_server
        activity_calls = []
        processor_calls = []

        def save_activity(value):
            activity_calls.append(value)
            if activity_error is not None:
                raise activity_error
            return {"id": value.get("id") or "activity-1", "name": value.get("name"), "status": value.get("status", "active")}

        def save_processor(value):
            processor_calls.append(value)
            if processor_error is not None:
                raise processor_error
            return {"id": value.get("id") or "processor-1", "name": value.get("name"), "status": value.get("status", "active")}

        with (
            mock.patch.object(admin_server.Handler, "_guard", return_value=True),
            mock.patch.object(admin_server.Handler, "authorized", return_value=True),
            mock.patch.object(admin_server.Handler, "_admin_origin_ok", return_value=origin_ok),
            mock.patch.object(admin_server.Handler, "_mfa_session_valid", return_value=not mfa),
            mock.patch.object(admin_server.admin_mfa, "configured", return_value=mfa),
            mock.patch.object(admin_server.compliance_operations, "upsert_processing_activity", side_effect=save_activity),
            mock.patch.object(admin_server.compliance_operations, "upsert_processor", side_effect=save_processor),
        ):
            server = admin_server.ThreadingHTTPServer(("127.0.0.1", 0), admin_server.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                body = json.dumps(payload).encode("utf-8")
                connection = http.client.HTTPConnection(*server.server_address, timeout=5)
                connection.request("POST", path, body=body, headers={"Content-Type": content_type})
                response = connection.getresponse()
                data = json.loads(response.read().decode("utf-8"))
                connection.close()
                return response.status, data, activity_calls, processor_calls
            finally:
                server.shutdown(); server.server_close(); thread.join(timeout=5)

    def test_processing_activity_create_delegates_payload(self):
        payload = {"name": "Gestion RDV", "status": "active"}
        status, data, calls, _ = self._post("/api/admin/compliance/processing-activity", payload)
        self.assertEqual(status, 201)
        self.assertTrue(data["ok"])
        self.assertEqual(data["activity"]["id"], "activity-1")
        self.assertEqual(calls, [payload])

    def test_processing_activity_update_is_idempotent_http_shape(self):
        payload = {"id": "activity-7", "name": "Gestion RDV", "status": "inactive"}
        status, data, calls, _ = self._post("/api/admin/compliance/processing-activity", payload)
        self.assertEqual(status, 200)
        self.assertEqual(data["activity"]["id"], "activity-7")
        self.assertEqual(calls, [payload])

    def test_processor_create_delegates_boolean_without_coercion(self):
        payload = {"name": "Prestataire", "transferRequired": False}
        status, data, _, calls = self._post("/api/admin/compliance/processor", payload)
        self.assertEqual(status, 201)
        self.assertFalse(calls[0]["transferRequired"])
        self.assertEqual(data["processor"]["id"], "processor-1")

    def test_validation_errors_are_sanitized(self):
        status, data, _, _ = self._post(
            "/api/admin/compliance/processing-activity", {"name": ""}, activity_error=ValueError("internal validation detail")
        )
        self.assertEqual(status, 400)
        self.assertEqual(data, {"ok": False, "error": "compliance_processing_activity_invalid"})
        self.assertNotIn("internal", json.dumps(data))

    def test_unexpected_processor_errors_do_not_leak_details(self):
        status, data, _, _ = self._post(
            "/api/admin/compliance/processor", {"name": "Prestataire"}, processor_error=RuntimeError("database /secret/path")
        )
        self.assertEqual(status, 500)
        self.assertEqual(data, {"ok": False, "error": "compliance_processor_unavailable"})
        self.assertNotIn("secret", json.dumps(data))

    def test_origin_gate_runs_before_register_write(self):
        status, data, activity_calls, processor_calls = self._post(
            "/api/admin/compliance/processing-activity", {"name": "Gestion RDV"}, origin_ok=False
        )
        self.assertEqual(status, 403)
        self.assertEqual(data, {"ok": False, "error": "origin_not_allowed"})
        self.assertEqual(activity_calls, [])
        self.assertEqual(processor_calls, [])

    def test_mfa_gate_runs_before_register_write(self):
        status, data, activity_calls, processor_calls = self._post(
            "/api/admin/compliance/processor", {"name": "Prestataire"}, mfa=True
        )
        self.assertEqual(status, 403)
        self.assertEqual(data, {"ok": False, "error": "two_factor_required"})
        self.assertEqual(activity_calls, [])
        self.assertEqual(processor_calls, [])

    def test_json_content_type_is_required(self):
        status, data, activity_calls, processor_calls = self._post(
            "/api/admin/compliance/processor", {"name": "Prestataire"}, content_type="text/plain"
        )
        self.assertEqual(status, 415)
        self.assertEqual(data, {"ok": False, "error": "content_type_not_allowed"})
        self.assertEqual(activity_calls, [])
        self.assertEqual(processor_calls, [])


if __name__ == "__main__":
    unittest.main()
