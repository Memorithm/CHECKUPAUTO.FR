import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import notification_broker as broker


class NotificationBrokerTest(unittest.TestCase):
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

    @patch.object(broker.email_transport, "send_email")
    def test_email_is_delivered_once_per_reference(self, send_email):
        send_email.return_value = {"ok": True}
        first = broker.send_email(
            "client@example.fr", "Rappel", "Votre contrôle approche.",
            category="control_reminder", reference="rdv-42",
        )
        second = broker.send_email(
            "client@example.fr", "Rappel", "Votre contrôle approche.",
            category="control_reminder", reference="rdv-42",
        )
        self.assertEqual(send_email.call_count, 1)
        self.assertEqual(first["status"], "sent")
        self.assertTrue(second["alreadySent"])

        raw = broker.DB.read_bytes()
        self.assertNotIn(b"client@example.fr", raw)
        self.assertNotIn(b"Votre controle approche", raw)

    @patch.object(broker.email_transport, "send_email")
    def test_failed_delivery_can_be_retried(self, send_email):
        send_email.side_effect = [RuntimeError("relay down"), {"ok": True}]
        with self.assertRaises(RuntimeError):
            broker.send_email(
                "client@example.fr", "Rappel", "Message",
                category="control_reminder", reference="rdv-7",
            )
        result = broker.send_email(
            "client@example.fr", "Rappel", "Message",
            category="control_reminder", reference="rdv-7",
        )
        self.assertEqual(result["status"], "sent")
        self.assertEqual(result["attempts"], 2)

    @patch.object(broker.email_transport, "send_email")
    def test_failure_diagnostics_redact_email_addresses(self, send_email):
        send_email.side_effect = RuntimeError("relay refused client@example.fr")
        with self.assertRaises(RuntimeError):
            broker.send_email(
                "client@example.fr", "Rappel", "Message",
                category="control_reminder", reference="rdv-redact",
            )
        self.assertNotIn(b"client@example.fr", broker.DB.read_bytes())
        with broker.connect() as db:
            row = db.execute("SELECT last_error FROM notification_delivery").fetchone()
        self.assertIn("[email]", row["last_error"])

    @patch.object(broker.email_transport, "send_email")
    def test_active_delivery_lease_prevents_parallel_send(self, send_email):
        key = broker._delivery_key("email", "review", "rdv-9", "client@example.fr")
        now = broker._now_iso()
        with broker.connect() as db:
            db.execute(
                """INSERT INTO notification_delivery(
                   idempotency_key,channel,category,reference,recipient_hash,status,attempts,created_at,last_attempt_at
                   ) VALUES(?,?,?,?,?,'delivering',1,?,?)""",
                (key, "email", "review", "rdv-9", "hash", now, now),
            )
        result = broker.send_email(
            "client@example.fr", "Avis", "Message",
            category="review", reference="rdv-9",
        )
        self.assertTrue(result["inFlight"])
        send_email.assert_not_called()

    @patch.object(broker.email_transport, "transport_status", return_value={
        "configured": True, "transport": "gmail-api", "requested": "auto",
        "smtpAvailable": False, "gmailAvailable": True, "state": "ready", "error": "",
    })
    def test_status_exposes_channel_readiness_without_recipient_data(self, transport_status):
        state = broker.status()
        self.assertTrue(state["channels"]["email"]["configured"])
        self.assertEqual(state["channels"]["email"]["transport"], "gmail-api")
        self.assertFalse(state["channels"]["push"]["configured"])
        self.assertIn("privacy", state)


if __name__ == "__main__":
    unittest.main()
