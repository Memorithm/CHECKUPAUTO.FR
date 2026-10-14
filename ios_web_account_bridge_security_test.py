"""Native bearer -> isolated WKWebView account-cookie bridge regression tests.

No screenshot-only mock, no cookie or bearer value in JSON, no browser OAuth.
"""
import datetime as dt
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import analytics_store as analytics
import customer_accounts
import customer_http
from customer_http_test import Handler
import security_guard


ROUTE = customer_http.MOBILE_WEB_SESSION_BRIDGE_ROUTE


class NativeWebSessionBridgeTests(unittest.TestCase):
    def test_invalid_method_and_query_fail_before_session_issue(self):
        for command, path in (("GET", ROUTE), ("POST", ROUTE + "?token=leak")):
            with self.subTest(command=command, path=path):
                h = Handler(path, command, {}, headers={"Authorization": "Bearer " + "a" * 48})
                with patch.object(customer_http.customer_accounts, "issue_session") as create:
                    self.assertTrue(customer_http.handle(h))
                    self.assertEqual(h.response["status"], 405 if command == "GET" else 403)
                    create.assert_not_called()

    def test_cookie_only_and_invalid_bearer_never_mint_browser_session(self):
        for headers in (
            {"Cookie": "checkupauto_customer=existing"},
            {"Authorization": "Bearer malformed"},
            {},
        ):
            with self.subTest(headers=headers):
                h = Handler(ROUTE, "POST", {}, headers=headers)
                with patch.object(customer_http.customer_accounts, "issue_session") as create:
                    customer_http.handle(h)
                    self.assertEqual(h.response["status"], 401)
                    create.assert_not_called()

    def test_browser_origin_csrf_cookie_and_payload_injection_rejected(self):
        valid = {"Authorization": "Bearer " + "a" * 48}
        cases = [
            ({"Sec-Fetch-Site": "cross-site"}, {}),
            ({"Origin": "https://malicious.invalid"}, {}),
            ({"Cookie": "untrusted=true"}, {}),
            ({}, {"redirect": "https://malicious.invalid"}),
        ]
        for added, payload in cases:
            with self.subTest(case=added or payload):
                h = Handler(ROUTE, "POST", payload, headers={**valid, **added})
                # The test Handler intentionally permits same-origin by default.
                h._admin_origin_ok = lambda: added.get("Origin") != "https://malicious.invalid"
                with patch.object(customer_http.customer_accounts, "authenticate_session", return_value="account-verified"), \
                     patch.object(customer_http.customer_accounts, "issue_session") as create:
                    customer_http.handle(h)
                    self.assertIn(h.response["status"], (403, 422))
                    create.assert_not_called()

    def test_mint_cookie_is_separate_short_lived_http_only_secure_and_host_only(self):
        h = Handler(ROUTE, "POST", {}, headers={"Authorization": "Bearer " + "a" * 48})
        new_session = {"token": "different-browser-token", "maxAge": 3600}
        with patch.object(customer_http.customer_accounts, "authenticate_session",
                          return_value="verified-account") as auth, \
             patch.object(customer_http.customer_accounts, "issue_session",
                          return_value=new_session) as mint:
            self.assertTrue(customer_http.handle(h))
        auth.assert_called_once_with("a" * 48)
        mint.assert_called_once_with("verified-account", lifetime_seconds=3600)
        self.assertEqual(h.response["status"], 200)
        self.assertEqual(h.response["json"], {"ok": True, "expiresIn": 3600})
        cookie = h.response["headers"]["Set-Cookie"]
        self.assertEqual(cookie.split(";")[0], "checkupauto_customer=different-browser-token")
        for clause in ("Path=/", "Max-Age=3600", "HttpOnly", "Secure", "SameSite=Lax"):
            self.assertIn(clause, cookie)
        self.assertNotIn("Domain=", cookie)
        self.assertNotIn("a" * 48, cookie)
        self.assertNotIn("different-browser-token", str(h.response["json"]))
        self.assertEqual(h.response["headers"]["Vary"], "Authorization")
        self.assertEqual(h.response["headers"]["Pragma"], "no-cache")

    def test_new_short_lived_cookie_has_real_server_side_expiry(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "data").mkdir()
        (root / "private").mkdir()
        env = patch.dict(os.environ, {
            "CYBERCHECK_DATA_DIR": str(root / "data"),
            "CYBERCHECK_PRIVATE_DIR": str(root / "private"),
        })
        env.start()
        self.addCleanup(env.stop)
        old_db = analytics.DB
        analytics.DB = root / "analytics.sqlite3"
        self.addCleanup(setattr, analytics, "DB", old_db)
        account = customer_accounts.create_from_verified_identity(
            "google", "native-web-bridge-1", "native@example.test", "Client",
            email_verified=True
        )
        native = customer_accounts.issue_session(account["accountId"])
        h = Handler(ROUTE, "POST", {}, headers={"Authorization": "Bearer " + native["token"]})
        customer_http.handle(h)
        self.assertEqual(h.response["status"], 200, h.response)
        web_token = h.response["headers"]["Set-Cookie"].split(";", 1)[0].split("=", 1)[1]
        self.assertNotEqual(web_token, native["token"])
        self.assertEqual(customer_accounts.authenticate_session(web_token), account["accountId"])
        self.assertEqual(customer_accounts.authenticate_session(native["token"]), account["accountId"])
        self.assertEqual(h.response["json"]["expiresIn"], 3600)
        customer_accounts.close_session(web_token)
        self.assertEqual(customer_accounts.authenticate_session(native["token"]), account["accountId"])
        with self.assertRaises(PermissionError):
            customer_accounts.authenticate_session(web_token)

    def test_session_lifetime_validation_refuses_unbounded_tokens(self):
        with patch.object(customer_accounts, "profile"):
            for ttl in (0, 12, -1, 24 * 60 * 60, "3600", True):
                with self.subTest(ttl=ttl):
                    with self.assertRaises(customer_accounts.CustomerAccountError):
                        customer_accounts.issue_session(
                            "00000000-0000-4000-8000-000000000001",
                            lifetime_seconds=ttl
                        )

    def test_native_cookie_minting_endpoint_has_strict_rate_limit(self):
        self.assertLessEqual(security_guard._ENDPOINT_LIMITS[ROUTE], 6)


if __name__ == "__main__":
    unittest.main()
