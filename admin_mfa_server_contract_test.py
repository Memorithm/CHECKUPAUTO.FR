from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent


class AdminMFAServerContractTest(unittest.TestCase):
    def test_admin_server_exposes_mfa_routes_and_central_guard(self):
        source = (ROOT / "admin_server.py").read_text(encoding="utf-8")
        for route in (
            "/api/admin/auth/2fa/status",
            "/api/admin/auth/2fa/qr",
            "/api/admin/auth/2fa/setup",
            "/api/admin/auth/2fa/confirm",
            "/api/admin/auth/2fa/verify",
            "/api/admin/auth/2fa/logout",
        ):
            self.assertIn(route, source)

        self.assertIn("import admin_mfa as admin_mfa", source)
        self.assertIn("admin_mfa.configured() and not self._mfa_session_valid()", source)
        self.assertIn("'two_factor_required'", source)
        self.assertIn("'Set-Cookie':admin_mfa.session_cookie(token)", source)
        self.assertIn("'Set-Cookie':admin_mfa.clear_session_cookie()", source)

    def test_mfa_endpoints_require_basic_auth_and_admin_origin(self):
        source = (ROOT / "admin_server.py").read_text(encoding="utf-8")
        get_status = source.index("if path=='/api/admin/auth/2fa/status':")
        status_block = source[get_status:get_status + 300]
        self.assertIn("if not self.authorized(): return self.require_auth()", status_block)

        post = source.index(" def do_POST(self):")
        guard = source.index("if path.startswith('/api/admin/'):", post)
        setup = source.index("if path=='/api/admin/auth/2fa/setup':", guard)
        block = source[guard:setup]
        self.assertIn("if not self.authorized(): return self.require_auth()", block)
        self.assertIn("if not self._admin_origin_ok()", block)
        self.assertIn("content_type_not_allowed", block)

    def test_mfa_auth_routes_are_only_exempt_from_second_factor_not_first_factor(self):
        source = (ROOT / "admin_server.py").read_text(encoding="utf-8")
        marker = "mfa_exempt={'/api/admin/auth/2fa/setup','/api/admin/auth/2fa/confirm','/api/admin/auth/2fa/verify','/api/admin/auth/2fa/logout'}"
        self.assertIn(marker, source)
        exempt = source.index(marker)
        basic = source.rfind("if not self.authorized(): return self.require_auth()", 0, exempt)
        origin = source.rfind("if not self._admin_origin_ok()", 0, exempt)
        self.assertGreater(basic, 0)
        self.assertGreater(origin, basic)

    def test_admin_delete_routes_require_second_factor_when_configured(self):
        source = (ROOT / "admin_server.py").read_text(encoding="utf-8")
        start = source.index(" def do_DELETE(self):")
        block = source[start:start + 900]
        self.assertIn("if not self.authorized(): return self.require_auth()", block)
        self.assertIn("if not self._admin_origin_ok()", block)
        self.assertIn(
            "admin_mfa.configured() and not self._mfa_session_valid()",
            block,
        )
        self.assertIn("return self.require_mfa()", block)

    def test_security_guard_rate_limits_mfa_attempts(self):
        source = (ROOT / "security_guard.py").read_text(encoding="utf-8")
        self.assertIn("'/api/admin/auth/2fa/setup': 4", source)
        self.assertIn("'/api/admin/auth/2fa/confirm': 8", source)
        self.assertIn("'/api/admin/auth/2fa/verify': 8", source)

    def test_admin_ui_contains_mfa_gate_without_embedded_secret(self):
        html = (ROOT / "admin" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "admin" / "mfa.js").read_text(encoding="utf-8")
        self.assertIn('id="mfaGate"', html)
        self.assertIn('id="mfaQr"', html)
        self.assertIn('id="mfaRecoveryCodes"', html)
        self.assertIn('/admin/mfa.js', html)
        self.assertIn('/api/admin/auth/2fa/status', script)
        self.assertIn('/api/admin/auth/2fa/setup', script)
        self.assertIn('/api/admin/auth/2fa/confirm', script)
        self.assertIn('/api/admin/auth/2fa/verify', script)
        self.assertNotIn("totp-secret", html)
        self.assertNotIn("recovery.json", html)
        self.assertNotIn("session-hmac-key", script)

    def test_security_ci_checks_mfa_javascript(self):
        workflow = (
            ROOT / ".github" / "workflows" / "security-ci.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("git ls-files '*.js'", workflow)
        self.assertIn('node --check "$file"', workflow)
        self.assertTrue(Path("admin/mfa.js").is_file())


if __name__ == "__main__":
    unittest.main()
