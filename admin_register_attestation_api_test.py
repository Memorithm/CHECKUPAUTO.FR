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


class AdminRegisterAttestationAPITest(unittest.TestCase):
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

    def _post(self, payload, *, result=None, error=None, mfa=False):
        admin_server = self.admin_server
        calls = []

        def attest(value):
            calls.append(value)
            if error is not None:
                raise error
            return result or {
                "current": True,
                "stale": False,
                "currentRegisterHash": "a" * 64,
                "attestedRegisterHash": "a" * 64,
                "reviewedAt": "2026-09-22T16:00:00+00:00",
                "evidenceHash": "b" * 64,
                "attestationCount": 1,
            }

        with (
            mock.patch.object(admin_server.Handler, "_guard", return_value=True),
            mock.patch.object(admin_server.Handler, "authorized", return_value=True),
            mock.patch.object(admin_server.Handler, "_admin_origin_ok", return_value=True),
            mock.patch.object(admin_server.Handler, "_mfa_session_valid", return_value=not mfa),
            mock.patch.object(admin_server.admin_mfa, "configured", return_value=mfa),
            mock.patch.object(admin_server.compliance_admin, "attest_operational_registers", side_effect=attest),
        ):
            server = admin_server.ThreadingHTTPServer(("127.0.0.1", 0), admin_server.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                body = json.dumps(payload).encode("utf-8")
                connection = http.client.HTTPConnection(*server.server_address, timeout=5)
                connection.request(
                    "POST",
                    "/api/admin/compliance/register-attestation",
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

    def test_reviewed_digest_reaches_attestation_boundary_unchanged(self):
        payload = {"confirm": "CURRENT-REGISTERS-REVIEWED", "expectedRegisterHash": "a" * 64}
        status, data, calls = self._post(payload)
        self.assertEqual(status, 201)
        self.assertTrue(data["ok"])
        self.assertTrue(data["attestation"]["current"])
        self.assertEqual(calls, [payload])

    def test_confirmation_failure_is_forbidden(self):
        status, data, _ = self._post(
            {"confirm": "NO", "expectedRegisterHash": "a" * 64},
            error=PermissionError("confirmation de revue requise"),
        )
        self.assertEqual(status, 403)
        self.assertEqual(data, {"ok": False, "error": "compliance_register_attestation_confirmation_required"})

    def test_stale_digest_conflict_is_explicit(self):
        status, data, _ = self._post(
            {"confirm": "CURRENT-REGISTERS-REVIEWED", "expectedRegisterHash": "a" * 64},
            error=RuntimeError("les registres ont changé depuis la revue"),
        )
        self.assertEqual(status, 409)
        self.assertEqual(data, {"ok": False, "error": "compliance_register_attestation_conflict"})

    def test_invalid_payload_is_sanitized(self):
        status, data, _ = self._post(
            {"confirm": "CURRENT-REGISTERS-REVIEWED", "expectedRegisterHash": "invalid"},
            error=ValueError("empreinte de registre invalide"),
        )
        self.assertEqual(status, 400)
        self.assertEqual(data, {"ok": False, "error": "compliance_register_attestation_invalid"})

    def test_mfa_gate_runs_before_attestation(self):
        payload = {"confirm": "CURRENT-REGISTERS-REVIEWED", "expectedRegisterHash": "a" * 64}
        status, data, calls = self._post(payload, mfa=True)
        self.assertEqual(status, 403)
        self.assertEqual(data, {"ok": False, "error": "two_factor_required"})
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
