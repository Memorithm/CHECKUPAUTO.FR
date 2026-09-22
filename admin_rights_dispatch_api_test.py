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


class AdminRightsDispatchAPITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private = tempfile.TemporaryDirectory()
        Path(cls.private.name, "admin-password").write_text("test-password\n", encoding="utf-8")
        cls.previous_private = os.environ.get("CYBERCHECK_PRIVATE_DIR")
        cls.previous_data = os.environ.get("CYBERCHECK_DATA_DIR")
        os.environ["CYBERCHECK_PRIVATE_DIR"] = cls.private.name
        os.environ["CYBERCHECK_DATA_DIR"] = cls.private.name
        cls.admin_server = importlib.import_module("admin_server")

    @classmethod
    def tearDownClass(cls):
        if cls.previous_private is None:
            os.environ.pop("CYBERCHECK_PRIVATE_DIR", None)
        else:
            os.environ["CYBERCHECK_PRIVATE_DIR"] = cls.previous_private
        if cls.previous_data is None:
            os.environ.pop("CYBERCHECK_DATA_DIR", None)
        else:
            os.environ["CYBERCHECK_DATA_DIR"] = cls.previous_data
        cls.private.cleanup()

    def _post(self, payload, *, dispatch_result=None, dispatch_error=None, mfa=False):
        admin_server = self.admin_server
        calls = []

        def execute(value):
            calls.append(value)
            if dispatch_error is not None:
                raise dispatch_error
            return dispatch_result or {"adapter": value.get("adapter"), "executed": True}

        with (
            mock.patch.object(admin_server.Handler, "_guard", return_value=True),
            mock.patch.object(admin_server.Handler, "authorized", return_value=True),
            mock.patch.object(admin_server.Handler, "_admin_origin_ok", return_value=True),
            mock.patch.object(admin_server.Handler, "_mfa_session_valid", return_value=not mfa),
            mock.patch.object(admin_server.admin_mfa, "configured", return_value=mfa),
            mock.patch.object(admin_server.rights_execution_dispatch, "execute", side_effect=execute),
        ):
            server = admin_server.ThreadingHTTPServer(("127.0.0.1", 0), admin_server.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                body = json.dumps(payload).encode("utf-8")
                connection = http.client.HTTPConnection(*server.server_address, timeout=5)
                connection.request(
                    "POST",
                    "/api/admin/compliance/request-execute",
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

    def test_central_adapter_payload_reaches_typed_dispatch_unchanged(self):
        payload = {
            "id": "a" * 32,
            "subjectRef": "11111111-1111-1111-1111-111111111111",
            "adapter": "mobile_installation",
        }
        status, data, calls = self._post(payload)
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(calls, [payload])

    def test_rectification_payload_keeps_correction_object_at_http_boundary(self):
        payload = {
            "id": "b" * 32,
            "subjectRef": "11111111-1111-1111-1111-111111111111",
            "adapter": "mobile_deadline_rectification",
            "correction": {"deadlineId": "deadline-1", "dueDate": "2027-01-15"},
        }
        status, _, calls = self._post(payload)
        self.assertEqual(status, 200)
        self.assertEqual(calls, [payload])

    def test_referral_wallet_payload_keeps_account_proof_at_http_boundary(self):
        payload = {
            "id": "c" * 32,
            "subjectRef": "11111111-1111-1111-1111-111111111111",
            "adapter": "referral_wallet",
            "accountId": "wallet-owner-proof",
        }
        status, _, calls = self._post(payload)
        self.assertEqual(status, 200)
        self.assertEqual(calls, [payload])

    def test_dispatch_validation_error_is_sanitized_as_bad_request(self):
        status, data, calls = self._post(
            {
                "id": "d" * 32,
                "subjectRef": "11111111-1111-1111-1111-111111111111",
                "adapter": "mobile_installation",
                "unexpected": "must-not-pass",
            },
            dispatch_error=ValueError("payload d'exécution de droit invalide"),
        )
        self.assertEqual(status, 400)
        self.assertEqual(data, {"ok": False, "error": "compliance_request_execution_invalid"})
        self.assertEqual(len(calls), 1)

    def test_mfa_gate_runs_before_dispatch(self):
        payload = {
            "id": "e" * 32,
            "subjectRef": "11111111-1111-1111-1111-111111111111",
            "adapter": "mobile_installation",
        }
        status, data, calls = self._post(payload, mfa=True)
        self.assertEqual(status, 403)
        self.assertEqual(data, {"ok": False, "error": "two_factor_required"})
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
