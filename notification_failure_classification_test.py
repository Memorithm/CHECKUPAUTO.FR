import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import notification_broker as broker


class NotificationFailureClassificationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_dir = broker.DATA_DIR
        self.old_db = broker.DB
        broker.DATA_DIR = Path(self.tmp.name)
        broker.DB = broker.DATA_DIR / "broker.sqlite3"
        broker.init_db()

    def tearDown(self):
        broker.DATA_DIR = self.old_dir
        broker.DB = self.old_db
        self.tmp.cleanup()

    def test_untyped_exception_text_cannot_select_configuration_class(self):
        for exc in (
            RuntimeError("aucun transport e-mail n'est configuré"),
            ValueError("transport non configuré"),
        ):
            with self.subTest(exc=type(exc).__name__):
                self.assertEqual(broker._classify_failure(exc), "transient")

    def test_typed_transport_errors_keep_explicit_classes(self):
        email_error = broker.email_transport.EmailDeliveryError(
            "configuration invalide",
            transport="smtp-relay",
            reason="configuration",
            configuration_error=True,
        )
        self.assertEqual(broker._classify_failure(email_error), "configuration")
        self.assertEqual(
            broker._classify_failure(broker.push_transport.APNSError(0, "CredentialsMissing")),
            "configuration",
        )
        self.assertEqual(
            broker._classify_failure(broker.push_transport.APNSError(400, "BadDeviceToken")),
            "permanent",
        )

    @patch.object(broker.email_transport, "send_email")
    def test_untyped_email_failure_does_not_open_configuration_circuit(self, send_email):
        send_email.side_effect = RuntimeError("aucun transport non configuré")
        with self.assertRaises(RuntimeError):
            broker.send_email(
                "client@example.fr",
                "Rappel",
                "Message",
                category="control_reminder",
                reference="typed-policy-regression",
            )
        with broker.connect() as db:
            delivery = db.execute(
                "SELECT failure_class,last_error FROM notification_delivery"
            ).fetchone()
            health = db.execute(
                "SELECT transient_failures,configuration_failures,circuit_opens FROM notification_transport_health"
            ).fetchone()
        self.assertEqual(delivery["failure_class"], "transient")
        self.assertEqual(delivery["last_error"], "RuntimeError")
        self.assertEqual(health["transient_failures"], 1)
        self.assertEqual(health["configuration_failures"], 0)
        self.assertEqual(health["circuit_opens"], 0)


if __name__ == "__main__":
    unittest.main()
