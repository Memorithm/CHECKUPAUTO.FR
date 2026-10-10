import os
import unittest
from unittest.mock import patch

import customer_http as http
import public_origin
from customer_password_http_test import form_handler


class PublicOriginTest(unittest.TestCase):
    def test_default_allow_list_is_first_party_and_canonical_first(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(public_origin.PUBLIC_ORIGINS_ENV, None)
            self.assertEqual(public_origin.canonical_origin(), "https://www.checkupauto.fr")
            self.assertEqual(public_origin.origin_for_host("evil.example"), "https://www.checkupauto.fr")
            self.assertEqual(public_origin.origin_for_host("test.checkupauto.fr"), "https://test.checkupauto.fr")
            self.assertEqual(public_origin.origin_for_host("WWW.CheckupAuto.fr"), "https://www.checkupauto.fr")

    def test_configured_origins_replace_defaults_and_reject_garbage(self):
        env = {public_origin.PUBLIC_ORIGINS_ENV: " https://stage.example/ , http://plain.example, https://a@b.example ,https://second.example:8443"}
        with patch.dict(os.environ, env, clear=False):
            self.assertEqual(public_origin.allowed_origins(), ("https://stage.example", "https://second.example:8443"))
            self.assertEqual(public_origin.origin_for_host("second.example:8443"), "https://second.example:8443")
            self.assertEqual(public_origin.origin_for_host("www.checkupauto.fr"), "https://stage.example")
            self.assertEqual(public_origin.origin_for_host("evil.example/x"), "https://stage.example")
            self.assertEqual(public_origin.origin_for_host(""), "https://stage.example")

    def test_invalid_configuration_falls_back_to_first_party_defaults(self):
        with patch.dict(os.environ, {public_origin.PUBLIC_ORIGINS_ENV: "javascript:alert(1),http://x"}, clear=False):
            self.assertEqual(public_origin.allowed_origins(), public_origin.DEFAULT_ALLOWED_ORIGINS)


class PasswordMailHostPoisoningTest(unittest.TestCase):
    """S-01: e-mailed links must not follow an attacker-supplied Host header."""

    def _reset_request(self, host):
        h = form_handler("/compte/mot-de-passe-oublie", {"email": "victim@example.test", "returnTo": ""}, headers={"Host": host})
        result = {"ok": True, "deliver": True, "email": "victim@example.test", "token": "r" * 43}
        with patch.dict(os.environ, {}, clear=False), \
             patch.object(http.email_gateway, "configured", return_value=True), \
             patch.object(http.customer_password_auth, "begin_reset", return_value=result), \
             patch.object(http.email_gateway, "send_email", return_value={"ok": True}) as send:
            os.environ.pop(public_origin.PUBLIC_ORIGINS_ENV, None)
            self.assertTrue(http.handle(h))
        self.assertEqual(h.response["status"], 200)
        send.assert_called_once()
        return send.call_args.args[2], send.call_args.args[3]

    def test_reset_link_ignores_hostile_host_header(self):
        text, html_body = self._reset_request("evil.example")
        self.assertNotIn("evil.example", text)
        self.assertNotIn("evil.example", html_body)
        self.assertIn("https://www.checkupauto.fr/compte/reinitialiser?token=" + "r" * 43, text)

    def test_reset_link_keeps_allow_listed_first_party_host(self):
        text, _ = self._reset_request("test.checkupauto.fr")
        self.assertIn("https://test.checkupauto.fr/compte/reinitialiser?token=", text)

    def test_registration_link_ignores_hostile_host_header(self):
        password = "A long customer passphrase 42"
        h = form_handler("/compte/inscription", {"email": "victim@example.test", "password": password, "passwordConfirm": password, "returnTo": ""}, headers={"Host": "evil.example"})
        pending = {"email": "victim@example.test", "token": "v" * 43, "purpose": "verify"}
        with patch.object(http.email_gateway, "configured", return_value=True), \
             patch.object(http.customer_password_auth, "begin_registration", return_value=pending), \
             patch.object(http.email_gateway, "send_email", return_value={"ok": True}) as send:
            self.assertTrue(http.handle(h))
        self.assertNotIn("evil.example", send.call_args.args[2])


if __name__ == "__main__":
    unittest.main()
