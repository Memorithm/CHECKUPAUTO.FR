import base64
import os
import unittest
from unittest.mock import Mock, patch

import email_gateway as mail


class EmailGatewayTest(unittest.TestCase):
    @patch.dict(os.environ, {}, clear=True)
    def test_requires_sender_configuration(self):
        self.assertIsNone(mail.load_config())

    @patch.dict(os.environ, {
        "CYBERCHECK_SMTP_FROM": "legacy@checkupauto.fr",
        "CYBERCHECK_SMTP_HOST": "legacy.example.fr",
        "CYBERCHECK_SMTP_MODE": "starttls",
        "CYBERCHECK_SMTP_USERNAME": "legacy-user",
        "CYBERCHECK_SMTP_PASSWORD": "legacy-secret",
    }, clear=True)
    @patch.object(mail.email_settings, "load", return_value={
        "transportMode": "smtp",
        "smtp": {
            "host": "smtp.example.fr",
            "port": 587,
            "sender": "contact@checkupauto.fr",
            "mode": "starttls",
            "username": "admin-user",
            "password": "admin-secret",
        },
    })
    def test_admin_settings_override_environment_without_restart(self, stored):
        cfg = mail.load_config()
        self.assertEqual(cfg.host, "smtp.example.fr")
        self.assertEqual(cfg.sender, "contact@checkupauto.fr")
        self.assertEqual(cfg.username, "admin-user")
        self.assertEqual(cfg.password, "admin-secret")
        self.assertEqual(mail._transport_mode(), "smtp")

    @patch.dict(os.environ, {
        "CYBERCHECK_EMAIL_TRANSPORT": "smtp",
        "CYBERCHECK_SMTP_FROM": "legacy@checkupauto.fr",
    }, clear=True)
    @patch.object(mail.email_settings, "load", return_value={
        "transportMode": "gmail",
        "smtp": {},
    })
    def test_admin_gmail_mode_suppresses_environment_smtp(self, stored):
        self.assertIsNone(mail.load_config())
        self.assertEqual(mail._transport_mode(), "gmail")

    @patch.object(mail.email_settings, "summary", return_value={"configured": True})
    @patch.object(mail.email_settings, "load", return_value={
        "transportMode": "smtp",
        "smtp": {
            "host": "smtp.example.fr",
            "port": 465,
            "sender": "contact@checkupauto.fr",
            "mode": "ssl",
            "username": "mailer",
            "password": "hidden-secret",
        },
    })
    def test_configuration_summary_never_exposes_password(self, stored, summary):
        public = mail.configuration_summary()
        self.assertEqual(public["source"], "admin")
        self.assertEqual(public["smtp"]["host"], "smtp.example.fr")
        self.assertTrue(public["smtp"]["passwordStored"])
        self.assertNotIn("hidden-secret", str(public))

    @patch.dict(os.environ, {"CYBERCHECK_SMTP_FROM": "rappel@checkupauto.fr"}, clear=True)
    def test_defaults_to_local_plain_relay(self):
        cfg = mail.load_config()
        self.assertEqual(cfg.host, "127.0.0.1")
        self.assertEqual(cfg.port, 25)
        self.assertEqual(cfg.mode, "plain")

    def test_rejects_invalid_recipient(self):
        self.assertFalse(mail.valid_email("not-an-email"))
        self.assertTrue(mail.valid_email("client@example.fr"))

    @patch.dict(os.environ, {"CYBERCHECK_SMTP_FROM": "rappel@checkupauto.fr"}, clear=True)
    @patch("email_gateway.smtplib.SMTP")
    def test_sends_through_local_relay(self, smtp_cls):
        client = smtp_cls.return_value
        client.send_message.return_value = {}
        result = mail.send_email("client@example.fr", "Rappel", "Votre contrôle approche.")
        smtp_cls.assert_called_once_with("127.0.0.1", 25, timeout=20.0)
        client.send_message.assert_called_once()
        self.assertEqual(result["transport"], "smtp-relay")

    @patch.dict(os.environ, {"CYBERCHECK_EMAIL_TRANSPORT": "gmail"}, clear=True)
    @patch.object(mail.google_integration, "settings", return_value={"gmailSender": "contact@checkupauto.fr"})
    @patch.object(mail.google_integration, "has_usable_scopes", return_value=True)
    @patch.object(mail.google_integration, "google_access_token", return_value="access-token")
    @patch("email_gateway.requests.post")
    def test_sends_through_gmail_api(self, post, access_token, has_usable_scopes, settings):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"id": "gmail-message-1"}
        post.return_value = response

        result = mail.send_email(
            "client@example.fr",
            "Rappel contrôle technique",
            "Votre contrôle approche.",
            "<p>Votre contrôle approche.</p>",
        )

        self.assertEqual(result["transport"], "gmail-api")
        self.assertEqual(result["messageId"], "gmail-message-1")
        kwargs = post.call_args.kwargs
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer access-token")
        decoded = base64.urlsafe_b64decode(kwargs["json"]["raw"].encode("ascii")).decode("utf-8")
        self.assertIn("From: contact@checkupauto.fr", decoded)
        self.assertIn("To: client@example.fr", decoded)
        self.assertNotIn("access-token", decoded)

    @patch.dict(os.environ, {"CYBERCHECK_EMAIL_TRANSPORT": "gmail"}, clear=True)
    @patch.object(mail.google_integration, "settings", return_value={"gmailSender": "contact@checkupauto.fr"})
    @patch.object(mail.google_integration, "has_usable_scopes", return_value=False)
    def test_gmail_requires_authorized_scope(self, has_usable_scopes, settings):
        self.assertFalse(mail.configured())
        with self.assertRaisesRegex(RuntimeError, "Gmail Checkup Auto non configuré"):
            mail.send_email("client@example.fr", "Rappel", "Message")

    @patch.dict(os.environ, {"CYBERCHECK_EMAIL_TRANSPORT": "auto"}, clear=True)
    @patch.object(mail.google_integration, "settings", return_value={"gmailSender": "contact@checkupauto.fr"})
    @patch.object(mail.google_integration, "has_usable_scopes", return_value=True)
    def test_status_reports_gmail_fallback_readiness(self, has_usable_scopes, settings):
        state = mail.transport_status()
        self.assertTrue(state["configured"])
        self.assertEqual(state["transport"], "gmail-api")
        self.assertTrue(state["gmailAvailable"])
        self.assertFalse(state["smtpAvailable"])

    @patch.dict(os.environ, {"CYBERCHECK_EMAIL_TRANSPORT": "invalid"}, clear=True)
    def test_rejects_unknown_transport_mode(self):
        self.assertFalse(mail.configured())
        state = mail.transport_status()
        self.assertEqual(state["requested"], "invalid")
        self.assertTrue(state["error"])

    @patch.dict(os.environ, {"CYBERCHECK_EMAIL_TRANSPORT": "gmail"}, clear=True)
    @patch.object(mail.google_integration, "settings", return_value={"gmailSender": "contact@checkupauto.fr"})
    @patch.object(mail.google_integration, "has_usable_scopes", return_value=True)
    @patch.object(mail.google_integration, "google_access_token", return_value="access-token")
    @patch("email_gateway.requests.post")
    def test_gmail_429_preserves_retry_after(self, post, access_token, has_usable_scopes, settings):
        response = Mock()
        response.status_code = 429
        response.headers = {"Retry-After": "120"}
        response.json.return_value = {
            "error": {"errors": [{"reason": "userRateLimitExceeded"}]}
        }
        post.return_value = response
        with self.assertRaises(mail.EmailDeliveryError) as caught:
            mail.send_email("client@example.fr", "Rappel", "Message")
        self.assertTrue(caught.exception.retryable)
        self.assertFalse(caught.exception.configuration_error)
        self.assertEqual(caught.exception.retry_after, "120")
        self.assertEqual(caught.exception.status, 429)

    @patch.dict(os.environ, {"CYBERCHECK_SMTP_FROM": "rappel@checkupauto.fr"}, clear=True)
    @patch("email_gateway.smtplib.SMTP")
    def test_smtp_550_is_permanent_recipient_failure(self, smtp_cls):
        client = smtp_cls.return_value
        client.send_message.return_value = {"client@example.fr": (550, b"mailbox unavailable")}
        with self.assertRaises(mail.EmailDeliveryError) as caught:
            mail.send_email("client@example.fr", "Rappel", "Message")
        self.assertTrue(caught.exception.permanent)
        self.assertFalse(caught.exception.retryable)
        self.assertEqual(caught.exception.status, 550)

    @patch.dict(os.environ, {"CYBERCHECK_SMTP_FROM": "rappel@checkupauto.fr"}, clear=True)
    @patch("email_gateway.smtplib.SMTP")
    def test_smtp_451_is_retryable_recipient_failure(self, smtp_cls):
        client = smtp_cls.return_value
        client.send_message.return_value = {"client@example.fr": (451, b"local error")}
        with self.assertRaises(mail.EmailDeliveryError) as caught:
            mail.send_email("client@example.fr", "Rappel", "Message")
        self.assertTrue(caught.exception.retryable)
        self.assertFalse(caught.exception.permanent)
        self.assertEqual(caught.exception.status, 451)


    @patch.dict(os.environ, {
        "CYBERCHECK_SMTP_FROM": "rappel@checkupauto.fr",
        "CYBERCHECK_SMTP_HOST": "smtp.example.fr",
        "CYBERCHECK_SMTP_PORT": "587",
        "CYBERCHECK_SMTP_MODE": "starttls",
        "CYBERCHECK_SMTP_USERNAME": "mailer-user",
        "CYBERCHECK_SMTP_PASSWORD": "runtime-only-secret",
    }, clear=True)
    @patch("email_gateway.smtplib.SMTP")
    def test_smtp_preflight_validates_tls_auth_and_sender_without_sending(self, smtp_cls):
        client = smtp_cls.return_value
        client.mail.return_value = (250, b"Sender OK")
        client.rset.return_value = (250, b"Reset OK")
        state = mail.smtp_preflight()
        self.assertTrue(state["ready"])
        self.assertTrue(state["tls"])
        self.assertTrue(state["authentication"])
        self.assertTrue(state["senderValidated"])
        client.starttls.assert_called_once()
        client.login.assert_called_once_with("mailer-user", "runtime-only-secret")
        client.mail.assert_called_once_with("rappel@checkupauto.fr")
        client.rset.assert_called_once()
        client.send_message.assert_not_called()

    @patch.dict(os.environ, {
        "CYBERCHECK_SMTP_FROM": "rappel@checkupauto.fr",
        "CYBERCHECK_SMTP_HOST": "smtp.example.fr",
        "CYBERCHECK_SMTP_PORT": "587",
        "CYBERCHECK_SMTP_MODE": "starttls",
    }, clear=True)
    @patch("email_gateway.smtplib.SMTP")
    def test_remote_smtp_send_requires_credentials_before_network_io(self, smtp_cls):
        with self.assertRaises(mail.EmailDeliveryError) as caught:
            mail.send_email("client@example.fr", "Rappel", "Message")
        self.assertTrue(caught.exception.configuration_error)
        self.assertFalse(caught.exception.permanent)
        self.assertEqual(caught.exception.reason, "authentication_required_for_remote_relay")
        smtp_cls.assert_not_called()

    @patch.dict(os.environ, {
        "CYBERCHECK_SMTP_FROM": "rappel@checkupauto.fr",
        "CYBERCHECK_SMTP_HOST": "smtp.example.fr",
        "CYBERCHECK_SMTP_PORT": "587",
        "CYBERCHECK_SMTP_MODE": "starttls",
    }, clear=True)
    def test_remote_smtp_status_reports_awaiting_credentials(self):
        state = mail.transport_status()
        self.assertTrue(state["configured"])
        self.assertEqual(state["transport"], "smtp-relay")
        self.assertEqual(state["state"], "awaiting_credentials")

    @patch.dict(os.environ, {
        "CYBERCHECK_SMTP_FROM": "rappel@checkupauto.fr",
        "CYBERCHECK_SMTP_HOST": "smtp.example.fr",
        "CYBERCHECK_SMTP_PORT": "587",
        "CYBERCHECK_SMTP_MODE": "starttls",
    }, clear=True)
    @patch("email_gateway.smtplib.SMTP")
    def test_remote_smtp_preflight_requires_credentials_by_default(self, smtp_cls):
        state = mail.smtp_preflight()
        self.assertFalse(state["ready"])
        self.assertEqual(state["state"], "awaiting_credentials")
        self.assertEqual(state["reason"], "authentication_required_for_remote_relay")
        smtp_cls.assert_not_called()

    @patch.dict(os.environ, {
        "CYBERCHECK_SMTP_FROM": "rappel@checkupauto.fr",
        "CYBERCHECK_SMTP_HOST": "smtp.example.fr",
        "CYBERCHECK_SMTP_PORT": "587",
        "CYBERCHECK_SMTP_MODE": "starttls",
        "CYBERCHECK_SMTP_ALLOW_UNAUTHENTICATED_REMOTE": "1",
    }, clear=True)
    @patch("email_gateway.smtplib.SMTP")
    def test_explicit_remote_unauthenticated_override_is_preflighted(self, smtp_cls):
        client = smtp_cls.return_value
        client.mail.return_value = (250, b"Sender OK")
        client.rset.return_value = (250, b"Reset OK")
        state = mail.smtp_preflight()
        self.assertTrue(state["ready"])
        self.assertFalse(state["authentication"])
        client.login.assert_not_called()
        client.send_message.assert_not_called()

    @patch.dict(os.environ, {
        "CYBERCHECK_SMTP_FROM": "rappel@checkupauto.fr",
        "CYBERCHECK_SMTP_USERNAME": "mailer-user",
        "CYBERCHECK_SMTP_PASSWORD": "runtime-only-secret",
        "CYBERCHECK_SMTP_MODE": "plain",
    }, clear=True)
    def test_smtp_auth_requires_encryption(self):
        with self.assertRaisesRegex(ValueError, "requires starttls or ssl"):
            mail.load_config()

    @patch.dict(os.environ, {"CYBERCHECK_EMAIL_TRANSPORT": "gmail"}, clear=True)
    @patch.object(mail.google_integration, "settings", return_value={"gmailSender": "contact@checkupauto.fr"})
    @patch.object(mail.google_integration, "has_scopes", return_value=True)
    @patch.object(mail.google_integration, "google_access_token", return_value="refreshed-access-token")
    @patch("email_gateway.requests.post")
    def test_gmail_preflight_forces_oauth_refresh_without_sending(self, post, access_token, has_scopes, settings):
        state = mail.gmail_preflight()
        self.assertTrue(state["ready"])
        access_token.assert_called_once_with([mail.GMAIL_SEND_SCOPE], force_refresh=True)
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
