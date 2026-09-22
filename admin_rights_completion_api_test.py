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


class AdminRightsCompletionAPITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private = tempfile.TemporaryDirectory()
        Path(cls.private.name, "admin-password").write_text("test-password\n", encoding="utf-8")
        cls.previous_private = os.environ.get("CYBERCHECK_PRIVATE_DIR")
        cls.previous_data = os.environ.get("CYBERCHECK_DATA_DIR")
        cls.previous_security = os.environ.get("CYBERCHECK_SECURITY_DIR")
        os.environ["CYBERCHECK_PRIVATE_DIR"] = cls.private.name
        os.environ["CYBERCHECK_DATA_DIR"] = cls.private.name
        os.environ["CYBERCHECK_SECURITY_DIR"] = str(Path(cls.private.name, "security"))
        cls.admin_server = importlib.import_module("admin_server")

    @classmethod
    def tearDownClass(cls):
        for name, previous in (
            ("CYBERCHECK_PRIVATE_DIR", cls.previous_private),
            ("CYBERCHECK_DATA_DIR", cls.previous_data),
            ("CYBERCHECK_SECURITY_DIR", cls.previous_security),
        ):
            if previous is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = previous
        cls.private.cleanup()

    def _post(
        self,
        payload,
        *,
        configure_result=None,
        mfa=False,
        origin_ok=True,
        content_type="application/json",
        path="/api/admin/compliance/request-plan",
        extra_headers=None,
    ):
        admin_server = self.admin_server
        calls = []

        def configure(value):
            calls.append(value)
            return configure_result or (
                200,
                {
                    "ok": True,
                    "completionPlan": {
                        "requestId": str(value.get("id") or ""),
                        "planComplete": True,
                        "globalCoverageComplete": False,
                        "closureReady": False,
                    },
                },
            )

        route = admin_server.payment_contract_http.rights_completion_admin_route
        headers = {"Content-Type": content_type}
        headers.update(extra_headers or {})
        with (
            mock.patch.object(admin_server.Handler, "_guard", return_value=True),
            mock.patch.object(admin_server.Handler, "authorized", return_value=True),
            mock.patch.object(admin_server.Handler, "_admin_origin_ok", return_value=origin_ok),
            mock.patch.object(admin_server.Handler, "_mfa_session_valid", return_value=not mfa),
            mock.patch.object(route.admin_mfa, "configured", return_value=mfa),
            mock.patch.object(route.rights_completion_admin_http, "configure", side_effect=configure),
        ):
            server = admin_server.ThreadingHTTPServer(("127.0.0.1", 0), admin_server.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                body = json.dumps(payload).encode("utf-8")
                connection = http.client.HTTPConnection(*server.server_address, timeout=5)
                connection.request("POST", path, body=body, headers=headers)
                response = connection.getresponse()
                data = json.loads(response.read().decode("utf-8"))
                connection.close()
                return response.status, data, calls
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_payload_reaches_completion_boundary_unchanged(self):
        payload = {
            "id": "a" * 32,
            "entries": [
                {"adapter": "mobile_installation", "disposition": "required"},
                {
                    "adapter": "mercure_customer_contact",
                    "disposition": "not_applicable",
                    "justification": "aucun dossier Mercure lié",
                },
            ],
        }
        status, data, calls = self._post(payload)
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(calls, [payload])
        self.assertFalse(data["completionPlan"]["globalCoverageComplete"])
        self.assertFalse(data["completionPlan"]["closureReady"])

    def test_conflict_response_is_forwarded_without_raw_justification(self):
        result = (409, {"ok": False, "error": "compliance_completion_plan_conflict"})
        payload = {
            "id": "b" * 32,
            "entries": [
                {
                    "adapter": "mercure_customer_contact",
                    "disposition": "not_applicable",
                    "justification": "sensitive operator note",
                }
            ],
        }
        status, data, calls = self._post(payload, configure_result=result)
        self.assertEqual(status, 409)
        self.assertEqual(data, result[1])
        self.assertEqual(len(calls), 1)
        self.assertNotIn("sensitive operator note", json.dumps(data))

    def test_mfa_gate_runs_before_completion_configuration(self):
        status, data, calls = self._post({"id": "c" * 32, "entries": []}, mfa=True)
        self.assertEqual(status, 403)
        self.assertEqual(data, {"ok": False, "error": "two_factor_required"})
        self.assertEqual(calls, [])

    def test_origin_gate_runs_before_completion_configuration(self):
        status, data, calls = self._post({"id": "d" * 32, "entries": []}, origin_ok=False)
        self.assertEqual(status, 403)
        self.assertEqual(data, {"ok": False, "error": "origin_not_allowed"})
        self.assertEqual(calls, [])

    def test_cross_site_fetch_is_denied_even_when_origin_helper_accepts(self):
        status, data, calls = self._post(
            {"id": "e" * 32, "entries": []},
            extra_headers={"Sec-Fetch-Site": "cross-site"},
        )
        self.assertEqual(status, 403)
        self.assertEqual(data, {"ok": False, "error": "origin_not_allowed"})
        self.assertEqual(calls, [])

    def test_non_json_content_type_is_denied_before_configuration(self):
        status, data, calls = self._post(
            {"id": "f" * 32, "entries": []},
            content_type="text/plain",
        )
        self.assertEqual(status, 415)
        self.assertEqual(data, {"ok": False, "error": "content_type_not_allowed"})
        self.assertEqual(calls, [])

    def test_query_string_is_not_accepted_on_mutation_route(self):
        status, data, calls = self._post(
            {"id": "1" * 32, "entries": []},
            path="/api/admin/compliance/request-plan?debug=1",
        )
        self.assertEqual(status, 400)
        self.assertEqual(data, {"ok": False, "error": "compliance_completion_plan_invalid"})
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
