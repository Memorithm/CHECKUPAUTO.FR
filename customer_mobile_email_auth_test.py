import unittest
from unittest.mock import patch

import customer_mobile_email_auth as auth
import customer_http


class MobileEmailAuthTests(unittest.TestCase):
    def test_login_reuses_audited_password_throttle_and_issues_mobile_session(self):
        with patch.object(auth.customer_password_auth, "authenticate",
                          return_value={"accountId": "account-1"}) as password, \
             patch.object(auth.customer_accounts, "issue_session",
                          return_value={"token": "keychain-token", "expiresAt": "future"}) as session:
            result = auth.sign_in({"email": "client@example.com", "password": "correct-password"},
                                  client_key="aabbccdd")
        password.assert_called_once_with("client@example.com", "correct-password",
                                         client_key="aabbccdd")
        session.assert_called_once_with("account-1")
        self.assertEqual(result["sessionToken"], "keychain-token")
        self.assertNotIn("password", result)

    def test_failed_password_never_issues_mobile_session(self):
        with patch.object(auth.customer_password_auth, "authenticate", side_effect=PermissionError), \
             patch.object(auth.customer_accounts, "issue_session") as issue:
            with self.assertRaises(PermissionError):
                auth.sign_in({"email": "client@example.com", "password": "wrong"})
        issue.assert_not_called()

    def test_extra_fields_and_non_strings_are_rejected(self):
        for payload in ({"email": "a@b.fr", "password": "password", "admin": True},
                        {"email": "a@b.fr", "password": 1234}, {},
                        {"email": "x" * 255, "password": "password"}):
            with self.subTest(payload=payload), self.assertRaises(auth.MobileEmailAuthInvalid):
                auth.sign_in(payload)

    def test_register_emails_verification_and_returns_no_sensitive_values(self):
        sent = []
        with patch.object(auth.email_gateway, "configured", return_value=True), \
             patch.object(auth.customer_password_auth, "begin_registration",
                          return_value={"purpose": "verify", "token": "private-verify",
                                        "email": "a@b.fr"}) as begin:
            result = auth.register({
                "email": "a@b.fr", "password": "example-strong-password",
                "passwordConfirm": "example-strong-password",
            }, send_confirmation=sent.append)
        begin.assert_called_once_with("a@b.fr", None, "example-strong-password")
        self.assertEqual(result, {"ok": True, "verificationRequired": True})
        self.assertEqual(sent[0]["token"], "private-verify")

    def test_registration_fails_when_mail_is_not_configured(self):
        with patch.object(auth.email_gateway, "configured", return_value=False), \
             patch.object(auth.customer_password_auth, "begin_registration") as begin:
            with self.assertRaises(auth.MobileEmailAuthUnavailable):
                auth.register({"email": "a@b.fr", "password": "secure-password",
                               "passwordConfirm": "secure-password"},
                              send_confirmation=lambda _: None)
            begin.assert_not_called()

    def test_registration_password_mismatch_rejected_before_database(self):
        with patch.object(auth.customer_password_auth, "begin_registration") as begin:
            with self.assertRaises(auth.MobileEmailAuthInvalid):
                auth.register({"email": "a@b.fr", "password": "one",
                               "passwordConfirm": "two"}, send_confirmation=lambda _: None)
            begin.assert_not_called()


class MobileEmailHttpTests(unittest.TestCase):
    class Handler:
        headers = {"Content-Type": "application/json"}
        _security_client = "aabbccdd"

        def __init__(self, path, command="POST", payload=None):
            self.path = path
            self.command = command
            self.payload = payload or {}
            self.response = None

        def _read_json(self):
            return self.payload

        def send_json(self, body, status=200):
            self.response = (status, body)

    def test_login_route_never_emits_browser_cookie(self):
        handler = self.Handler(customer_http.MOBILE_EMAIL_SIGNIN_ROUTE,
                               payload={"email": "a@b.fr", "password": "secret"})
        with patch.object(customer_http.customer_mobile_email_auth, "sign_in",
                          return_value={"ok": True, "sessionToken": "verified"}) as login:
            self.assertTrue(customer_http.handle(handler))
        login.assert_called_once_with(handler.payload, client_key="aabbccdd")
        self.assertEqual(handler.response[0], 200)

    def test_registration_mail_path_is_server_only(self):
        handler = self.Handler(customer_http.MOBILE_EMAIL_REGISTER_ROUTE,
                               payload={"email": "a@b.fr", "password": "valid-password",
                                        "passwordConfirm": "valid-password"})
        with patch.object(customer_http.customer_mobile_email_auth, "register",
                          return_value={"ok": True, "verificationRequired": True}) as register:
            self.assertTrue(customer_http.handle(handler))
        self.assertEqual(handler.response[0], 200)
        self.assertTrue(callable(register.call_args.kwargs["send_confirmation"]))

    def test_invalid_method_returns_405_without_authentication(self):
        handler = self.Handler(customer_http.MOBILE_EMAIL_SIGNIN_ROUTE, command="GET")
        with patch.object(customer_http.customer_mobile_email_auth, "sign_in") as login:
            self.assertTrue(customer_http.handle(handler))
            self.assertEqual(handler.response[0], 405)
            login.assert_not_called()

    def test_authentication_failure_responds_generically(self):
        handler = self.Handler(customer_http.MOBILE_EMAIL_SIGNIN_ROUTE,
                               payload={"email": "a@b.fr", "password": "bad"})
        with patch.object(customer_http.customer_mobile_email_auth, "sign_in",
                          side_effect=PermissionError):
            customer_http.handle(handler)
        self.assertEqual(handler.response, (401, {
            "ok": False, "error": "mobile_email_auth_failed"
        }))


if __name__ == "__main__":
    unittest.main()
