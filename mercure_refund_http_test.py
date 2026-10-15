"""Loopback HTTP tests for the Mercure refund routes and the 2FA step-up."""
import base64
from contextlib import ExitStack
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import admin_mfa
import admin_server
import mercure_refund
from admin_http_test_support import AdminHttpHarness


class StepUpTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = patch.dict(os.environ, {"CYBERCHECK_ADMIN_MFA_DIR": str(Path(tmp.name) / "mfa")})
        env.start()
        self.addCleanup(env.stop)
        self.secret = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
        admin_mfa._atomic_write(admin_mfa._secret_path(), self.secret.encode())

    def test_fresh_code_once_and_never_a_recovery_code(self):
        now = 1_800_000_000
        code = admin_mfa.totp_at(self.secret, now)
        self.assertTrue(admin_mfa.verify_step_up(code, now=now))
        self.assertFalse(admin_mfa.verify_step_up(code, now=now))
        self.assertFalse(admin_mfa.verify_step_up("ABCDEFGHJKLM", now=now + 60))
        self.assertTrue(admin_mfa.verify_step_up(admin_mfa.totp_at(self.secret, now + 30), now=now + 30))

    def test_not_configured_is_refused(self):
        admin_mfa._secret_path().unlink()
        self.assertFalse(admin_mfa.verify_step_up("123456"))


class RefundRoutesTest(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.object(admin_server, "PRIVATE_DIR", root))
        self.stack.enter_context(patch.dict(os.environ, {
            "CYBERCHECK_PRIVATE_DIR": str(root),
            "CYBERCHECK_ADMIN_MFA_DIR": str(root / "mfa"),
            mercure_refund.ENABLE_ENV: "true"}))
        self.stack.enter_context(patch.object(
            admin_server.security, "evaluate",
            return_value={"allow": True, "client": "", "path": "", "risk": 0}))
        password = root / "admin-password"
        password.write_text(admin_server.PASSWORD + "\n", encoding="utf-8")
        password.chmod(0o600)
        admin_mfa._atomic_write(admin_mfa._secret_path(),
                                base64.b32encode(b"12345678901234567890").decode().rstrip("=").encode())
        self.cookie = admin_mfa.session_cookie(admin_mfa.issue_session(now=int(time.time()))).split(";", 1)[0]
        self.lookup = self.stack.enter_context(patch.object(
            mercure_refund, "lookup", return_value={"ok": True, "appointment": {}, "confirmation": None}))
        self.execute = self.stack.enter_context(patch.object(mercure_refund, "execute"))
        self.http = AdminHttpHarness()
        self.addCleanup(self.http.close)

    def request(self, method, path, body=None, *, cookie=None, auth=True, headers=None):
        return self.http.request(method, path, body, cookie=self.cookie if cookie is None else cookie,
                                 auth=auth, headers=headers)

    def csrf(self):
        status, data, response = self.request("GET", "/api/admin/mercure-refunds/csrf")
        self.assertEqual(status, 200)
        self.assertTrue(data["enabled"])
        self.assertEqual(response.get("Cache-Control"), "no-store")
        return data["csrfToken"]

    def test_lookup_needs_login_mfa_and_csrf(self):
        body = {"appointmentId": "6100654", "date": "2026-10-21"}
        self.assertEqual(self.request("POST", "/api/admin/mercure-refunds/lookup", body, auth=False)[0], 401)
        self.assertEqual(self.request("POST", "/api/admin/mercure-refunds/lookup", body, cookie="")[0], 403)
        status, data, _ = self.request("POST", "/api/admin/mercure-refunds/lookup", body)
        self.assertEqual((status, data["error"]), (403, "refund_csrf_invalid"))
        token = self.csrf()
        status, data, _ = self.request("POST", "/api/admin/mercure-refunds/lookup", body,
                                       headers={"X-CheckupAuto-Refund-CSRF": token,
                                                "Origin": "https://evil.example"})
        self.assertEqual((status, data["error"]), (403, "origin_not_allowed"))
        self.lookup.assert_not_called()
        status, data, _ = self.request("POST", "/api/admin/mercure-refunds/lookup", body,
                                       headers={"X-CheckupAuto-Refund-CSRF": token})
        self.assertEqual(status, 200)
        self.lookup.assert_called_once()
        self.execute.assert_not_called()

    def test_refused_while_two_factor_is_not_enrolled(self):
        admin_mfa._secret_path().unlink()
        status, data, _ = self.request("GET", "/api/admin/mercure-refunds/csrf", cookie="")
        self.assertEqual((status, data["error"]), (403, "two_factor_not_configured"))

    def test_execute_uses_the_step_up_check_and_rejects_get(self):
        self.execute.return_value = {"ok": True}
        token = self.csrf()
        self.assertEqual(self.request("GET", "/api/admin/mercure-refunds/execute")[0], 404)
        status, _, _ = self.request("POST", "/api/admin/mercure-refunds/execute",
                                    {"confirmation": "x", "appointmentId": "1", "amount": "80", "code": "1"},
                                    headers={"X-CheckupAuto-Refund-CSRF": token})
        self.assertEqual(status, 200)
        self.assertIs(self.execute.call_args.kwargs["verify_code"], admin_mfa.verify_step_up)


if __name__ == "__main__":
    unittest.main()
