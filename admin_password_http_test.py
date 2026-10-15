"""Real HTTP loopback tests for the admin-password page and mutation."""
import base64
from contextlib import ExitStack
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

import admin_mfa
import admin_password
import admin_server
from admin_http_test_support import AdminHttpHarness


class AdminPasswordHTTPTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        folder = self.stack.enter_context(tempfile.TemporaryDirectory())
        root = Path(folder)
        self.stack.enter_context(patch.object(admin_server, "PRIVATE_DIR", root))
        # These tests exercise the Handler's Basic/MFA/CSRF boundaries, not the
        # global IP-burst Sentinel. Avoid polluting its shared in-memory limits
        # for subsequent HTTP tests in the full 2800+ test suite.
        self.stack.enter_context(patch.object(
            admin_server.security, "evaluate",
            return_value={"allow": True, "client": "", "path": "", "risk": 0}))
        self.old = admin_server.PASSWORD
        self.password_file = root / "admin-password"
        self.password_file.write_text(self.old + "\n", encoding="utf-8")
        self.password_file.chmod(0o600)
        self.stack.enter_context(patch.object(admin_mfa, "configured", return_value=False))
        self.stack.enter_context(patch.object(admin_mfa, "required", return_value=False))
        self.invalidate = self.stack.enter_context(patch.object(
            admin_mfa, "invalidate_all_sessions"))
        self.http = AdminHttpHarness()
        self.addCleanup(self.http.close)

    def request(self, method, url, body=None, *, headers=None, auth=True):
        return self.http.request(method, url, body, auth=auth, headers=headers)

    def challenge(self):
        status, data, response = self.request("GET", "/api/admin/auth/password/csrf")
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(len(data["csrfToken"]), 64)
        self.assertEqual(response.get("Cache-Control"), "no-store")
        return data["csrfToken"]

    def post(self, token, *, current=None, new="Test-HTTP-next-Password#11",
             confirm=None, headers=None):
        body = {"currentPassword": self.old if current is None else current,
                "newPassword": new,
                "confirmPassword": new if confirm is None else confirm}
        return self.request(
            "POST", "/api/admin/auth/password/change", body,
            headers={"X-CheckupAuto-Admin-Password-CSRF": token, **(headers or {})},
        )

    def test_success_rotates_credential_and_invalidates_mfa(self):
        token = self.challenge()
        status, data, response = self.post(token)
        self.assertEqual(status, 200)
        self.assertTrue(data["reloginRequired"])
        self.assertEqual(response.get("Cache-Control"), "no-store")
        self.assertIn("Max-Age=0", response.get("Set-Cookie"))
        self.invalidate.assert_called_once()
        self.assertFalse(admin_password.verify(self.old, path=self.password_file))
        status, _, _ = self.request("GET", "/api/admin/auth/password/csrf")
        self.assertEqual(status, 401)
        next_password = "Test-HTTP-next-Password#11"
        encoded = base64.b64encode(("admin:" + next_password).encode()).decode()
        status, data, _ = self.request(
            "GET", "/api/admin/auth/password/csrf", auth=False,
            headers={"Authorization": "Basic " + encoded})
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])

    def test_bad_csrf_forgery_and_wrong_old_password_fail_closed(self):
        status, data, _ = self.post("0" * 64)
        self.assertEqual((status, data["error"]), (403, "admin_password_csrf_invalid"))
        token = self.challenge()
        status, data, _ = self.post(token, current="Not-the-real-password")
        self.assertEqual((status, data["error"]), (403, "admin_password_current_invalid"))
        status, _, _ = self.post(token, headers={"Origin": "https://evil.example"})
        self.assertEqual(status, 403)
        status, _, _ = self.post(token, headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(status, 403)
        self.assertTrue(admin_password.verify(self.old, path=self.password_file))
        self.invalidate.assert_not_called()

    def test_mfa_is_required_when_configured(self):
        token = self.challenge()
        with patch.object(admin_mfa, "configured", return_value=True), patch.object(
            admin_server.Handler, "_mfa_session_valid", return_value=False
        ):
            status, _, _ = self.request("GET", "/api/admin/auth/password/csrf")
            self.assertEqual(status, 403)
            status, _, _ = self.post(token)
            self.assertEqual(status, 403)
        self.assertTrue(admin_password.verify(self.old, path=self.password_file))
        self.invalidate.assert_not_called()

    def test_invalid_payload_never_changes_private_file(self):
        token = self.challenge()
        status, data, _ = self.request(
            "POST", "/api/admin/auth/password/change",
            {"currentPassword": self.old, "newPassword": "Z" * 14},
            headers={"X-CheckupAuto-Admin-Password-CSRF": token},
        )
        self.assertEqual(status, 400)
        self.assertEqual(data["error"], "admin_password_body_invalid")
        self.assertTrue(admin_password.verify(self.old, path=self.password_file))

    def test_static_admin_navigation_has_protected_password_section(self):
        html = (Path(__file__).parent / "admin" / "index.html").read_text(encoding="utf-8")
        js = (Path(__file__).parent / "admin" / "password-change.js").read_text(encoding="utf-8")
        self.assertIn('href="#admin-password"', html)
        self.assertIn('id="adminPasswordCurrent"', html)
        self.assertIn('id="adminPasswordNew"', html)
        self.assertIn('id="adminPasswordConfirm"', html)
        self.assertIn('id="adminPasswordChange" type="button"', html)
        self.assertIn('/admin/password-change.js', html)
        self.assertIn("'/api/admin/auth/password/csrf'", js)
        self.assertIn("'/api/admin/auth/password/change'", js)
        self.assertIn("old.value = ''", js)
        self.assertIn("next.value = ''", js)
        self.assertIn("confirm.value = ''", js)


if __name__ == "__main__":
    unittest.main()
