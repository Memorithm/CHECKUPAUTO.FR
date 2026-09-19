import base64
import os
import unittest
from unittest.mock import Mock, patch

import email_gateway as mail


class EmailGatewayTest(unittest.TestCase):
    @patch.dict(os.environ, {}, clear=True)
    def test_requires_sender_configuration(self):
        self.assertIsNone(mail.load_config())

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
    @patch.object(mail.google_integration, "has_scopes", return_value=True)
    @patch.object(mail.google_integration, "google_access_token", return_value="access-token")
    @patch("email_gateway.requests.post")
    def test_sends_through_gmail_api(self, post, access_token, has_scopes, settings):
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
    @patch.object(mail.google_integration, "has_scopes", return_value=False)
    def test_gmail_requires_authorized_scope(self, has_scopes, settings):
        self.assertFalse(mail.configured())
        with self.assertRaisesRegex(RuntimeError, "Gmail Checkup Auto non configuré"):
            mail.send_email("client@example.fr", "Rappel", "Message")

    @patch.dict(os.environ, {"CYBERCHECK_EMAIL_TRANSPORT": "auto"}, clear=True)
    @patch.object(mail.google_integration, "settings", return_value={"gmailSender": "contact@checkupauto.fr"})
    @patch.object(mail.google_integration, "has_scopes", return_value=True)
    def test_status_reports_gmail_fallback_readiness(self, has_scopes, settings):
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


if __name__ == "__main__":
    unittest.main()
