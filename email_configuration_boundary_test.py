import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import email_gateway as mail
import notification_broker as broker


class EmailConfigurationBoundaryTest(unittest.TestCase):
    @patch.dict(os.environ, {"CYBERCHECK_EMAIL_TRANSPORT": "invalid-mode"}, clear=True)
    def test_invalid_transport_mode_is_typed_configuration_failure(self):
        with self.assertRaises(mail.EmailDeliveryError) as caught:
            mail.send_email("client@example.fr", "Rappel", "Message")
        self.assertTrue(caught.exception.configuration_error)
        self.assertEqual(caught.exception.failure_class, "configuration")
        self.assertEqual(caught.exception.transport, "email:none")
        self.assertEqual(caught.exception.reason, "configuration")
        self.assertNotIn("invalid-mode", str(caught.exception))

    @patch.dict(os.environ, {
        "CYBERCHECK_EMAIL_TRANSPORT": "smtp",
        "CYBERCHECK_SMTP_FROM": "rappel@checkupauto.fr",
        "CYBERCHECK_SMTP_MODE": "invalid-mode",
    }, clear=True)
    def test_invalid_smtp_configuration_is_typed_without_raw_detail(self):
        with self.assertRaises(mail.EmailDeliveryError) as caught:
            mail.send_email("client@example.fr", "Rappel", "Message")
        self.assertTrue(caught.exception.configuration_error)
        self.assertEqual(caught.exception.transport, "smtp-relay")
        self.assertEqual(caught.exception.reason, "configuration")
        self.assertNotIn("invalid-mode", str(caught.exception))

    @patch.dict(os.environ, {"CYBERCHECK_EMAIL_TRANSPORT": "invalid-mode"}, clear=True)
    def test_broker_opens_configuration_circuit_only_from_typed_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_dir, old_db = broker.DATA_DIR, broker.DB
            broker.DATA_DIR = Path(tmp)
            broker.DB = broker.DATA_DIR / "broker.sqlite3"
            try:
                broker.init_db()
                with self.assertRaises(mail.EmailDeliveryError):
                    broker.send_email(
                        "client@example.fr",
                        "Rappel",
                        "Message",
                        category="control_reminder",
                        reference="invalid-email-config",
                    )
                with broker.connect() as db:
                    delivery = db.execute(
                        "SELECT failure_class,last_error FROM notification_delivery"
                    ).fetchone()
                    health = db.execute(
                        "SELECT configuration_failures,transient_failures,circuit_opens,open_until FROM notification_transport_health"
                    ).fetchone()
                self.assertEqual(delivery["failure_class"], "configuration")
                self.assertIn("class=configuration", delivery["last_error"])
                self.assertNotIn("invalid-mode", delivery["last_error"])
                self.assertEqual(health["configuration_failures"], 1)
                self.assertEqual(health["transient_failures"], 0)
                self.assertEqual(health["circuit_opens"], 1)
                self.assertTrue(health["open_until"])
            finally:
                broker.DATA_DIR = old_dir
                broker.DB = old_db


if __name__ == "__main__":
    unittest.main()
