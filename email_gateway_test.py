import os
import unittest
from unittest.mock import patch

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
        result = mail.send_email(
            "client@example.fr",
            "Rappel",
            "Votre contrôle approche.",
        )
        smtp_cls.assert_called_once_with("127.0.0.1", 25, timeout=20.0)
        client.send_message.assert_called_once()
        self.assertEqual(result["transport"], "smtp-relay")


if __name__ == "__main__":
    unittest.main()
