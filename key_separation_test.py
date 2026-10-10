"""S-07: purpose-bound keys for CSRF tokens."""
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

import customer_accounts
import customer_oidc_admin_http


class KeySeparationTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        env = mock.patch.dict(os.environ, {"CYBERCHECK_PRIVATE_DIR": str(self.root), "CYBERCHECK_DATA_DIR": str(self.root / "data")})
        env.start(); self.addCleanup(env.stop)

    def test_customer_csrf_uses_a_derived_subkey_not_the_master_key(self):
        token = "t" * 43
        csrf = customer_accounts.csrf_token(token)
        self.assertNotEqual(csrf, customer_accounts._hmac("csrf", token))
        self.assertNotEqual(customer_accounts._subkey("csrf"), customer_accounts._ensure_key())
        self.assertNotEqual(customer_accounts._subkey("csrf"), customer_accounts._subkey("other"))
        self.assertTrue(customer_accounts.verify_csrf(token, csrf))
        self.assertFalse(customer_accounts.verify_csrf("u" * 43, csrf))

    def test_admin_csrf_key_is_random_persistent_and_private(self):
        first = customer_oidc_admin_http.csrf_secret()
        self.assertRegex(first, r"^[0-9a-f]{64}$")
        self.assertEqual(customer_oidc_admin_http.csrf_secret(), first)
        mode = stat.S_IMODE(customer_oidc_admin_http._csrf_key_path().stat().st_mode)
        self.assertEqual(mode, 0o600)

    def test_admin_csrf_key_refuses_symlink(self):
        target = self.root / "elsewhere"; target.write_bytes(b"x" * 32)
        path = customer_oidc_admin_http._csrf_key_path(); path.parent.mkdir(parents=True)
        path.symlink_to(target)
        with self.assertRaises(OSError):
            customer_oidc_admin_http.csrf_secret()


class AdminOidcCsrfHttpTest(unittest.TestCase):
    """The admin OIDC page hands out CSRF tokens keyed by the dedicated key."""

    def test_issued_token_is_keyed_by_dedicated_secret_not_password(self):
        import base64
        import admin_server
        from admin_http_test_support import AdminHttpHarness
        harness = AdminHttpHarness(); self.addCleanup(harness.close)
        status, body, _ = harness.request("GET", customer_oidc_admin_http.ROUTE)
        self.assertEqual(status, 200, body)
        auth = "Basic " + base64.b64encode(f"{admin_server.USER}:{admin_server.PASSWORD}".encode()).decode()
        headers = {"Authorization": auth, "Cookie": ""}
        expected = customer_oidc_admin_http.csrf_token(customer_oidc_admin_http.csrf_secret(), headers)
        legacy = customer_oidc_admin_http.csrf_token(admin_server.PASSWORD, headers)
        self.assertEqual(body["csrfToken"], expected)
        self.assertNotEqual(body["csrfToken"], legacy)

if __name__ == "__main__":
    unittest.main()
