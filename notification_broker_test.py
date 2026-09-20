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

    def test_seconds_until_rounds_up_to_avoid_early_retry(self):
        now = broker.datetime.datetime(2026, 9, 19, 16, 0, 0, 800000, tzinfo=broker.datetime.timezone.utc)
        target = "2026-09-19T16:02:00.800000+00:00"
        self.assertEqual(broker._seconds_until(target, now), 120)
        later = now + broker.datetime.timedelta(microseconds=100000)
        self.assertEqual(broker._seconds_until(target, later), 120)

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
    def test_failed_delivery_obeys_backoff_then_can_be_retried(self, send_email):
        send_email.side_effect = [RuntimeError("relay down"), {"ok": True}]
        with self.assertRaises(RuntimeError):
            broker.send_email(
                "client@example.fr", "Rappel", "Message",
                category="control_reminder", reference="rdv-7",
            )
        deferred = broker.send_email(
            "client@example.fr", "Rappel", "Message",
            category="control_reminder", reference="rdv-7",
        )
        self.assertTrue(deferred["deferred"])
        self.assertGreater(deferred["retryAfterSeconds"], 0)
        self.assertEqual(send_email.call_count, 1)
        with broker.connect() as db:
            db.execute("UPDATE notification_delivery SET next_attempt_at='' WHERE reference='rdv-7'")
        result = broker.send_email(
            "client@example.fr", "Rappel", "Message",
            category="control_reminder", reference="rdv-7",
        )
        self.assertEqual(result["status"], "sent")
        self.assertEqual(result["attempts"], 2)

    @patch.object(broker.email_transport, "send_email")
    def test_failure_diagnostics_never_persist_arbitrary_exception_text(self, send_email):
        send_email.side_effect = RuntimeError("relay refused client@example.fr bearer-secret-123")
        with self.assertRaises(RuntimeError):
            broker.send_email(
                "client@example.fr", "Rappel", "Message",
                category="control_reminder", reference="rdv-redact",
            )
        raw = broker.DB.read_bytes()
        self.assertNotIn(b"client@example.fr", raw)
        self.assertNotIn(b"bearer-secret-123", raw)
        with broker.connect() as db:
            row = db.execute("SELECT last_error FROM notification_delivery").fetchone()
            health = db.execute("SELECT last_error FROM notification_transport_health").fetchone()
        self.assertEqual(row["last_error"], "RuntimeError")
        self.assertEqual(health["last_error"], "RuntimeError")

    @patch.object(broker.email_transport, "send_email")
    def test_typed_email_diagnostic_keeps_only_bounded_structured_fields(self, send_email):
        send_email.side_effect = broker.email_transport.EmailDeliveryError(
            "recipient client@example.fr rejected with secret=abc",
            transport="smtp-relay", status=550, reason="recipient_refused", permanent=True,
        )
        with self.assertRaises(broker.email_transport.EmailDeliveryError):
            broker.send_email(
                "client@example.fr", "Rappel", "Message",
                category="control_reminder", reference="rdv-typed-diagnostic",
            )
        with broker.connect() as db:
            row = db.execute("SELECT last_error FROM notification_delivery").fetchone()
        self.assertEqual(
            row["last_error"],
            "EmailDeliveryError transport=smtp-relay class=permanent status=550 reason=recipient_refused",
        )
        self.assertNotIn("client@example.fr", row["last_error"])
        self.assertNotIn("secret=abc", row["last_error"])

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


    @patch.object(broker.push_transport, "send")
    def test_push_is_delivered_once_without_persisting_device_token(self, send_push):
        send_push.return_value = {"ok": True}
        token = "ab" * 32
        first = broker.send_push(
            token,
            "Rappel",
            "Votre contrôle approche.",
            category="ct_due",
            reference="mobile-42",
            notification_category="CHECKUPAUTO_CT_DUE",
        )
        second = broker.send_push(
            token,
            "Rappel",
            "Votre contrôle approche.",
            category="ct_due",
            reference="mobile-42",
            notification_category="CHECKUPAUTO_CT_DUE",
        )
        self.assertEqual(send_push.call_count, 1)
        self.assertEqual(
            send_push.call_args.kwargs["notification_category"],
            "CHECKUPAUTO_CT_DUE",
        )
        self.assertEqual(first["status"], "sent")
        self.assertTrue(second["alreadySent"])
        self.assertNotIn(token.encode(), broker.DB.read_bytes())


    @patch.object(broker.push_transport, "send")
    def test_apns_retry_after_defers_same_delivery(self, send_push):
        send_push.side_effect = broker.push_transport.APNSError(503, "ServiceUnavailable", retry_after="120")
        token = "cd" * 32
        with self.assertRaises(broker.push_transport.APNSError):
            broker.send_push(token, "Rappel", "Message", category="ct_due", reference="mobile-retry")
        deferred = broker.send_push(token, "Rappel", "Message", category="ct_due", reference="mobile-retry")
        self.assertTrue(deferred["deferred"])
        self.assertGreaterEqual(deferred["retryAfterSeconds"], 119)
        self.assertEqual(send_push.call_count, 1)
        self.assertEqual(broker.status()["counts"]["deferred"], 1)

    @patch.object(broker.push_transport, "send")
    def test_apns_circuits_are_separated_by_environment(self, send_push):
        send_push.side_effect = broker.push_transport.APNSError(503, "ServiceUnavailable")
        for index in range(broker.resilience.CIRCUIT_THRESHOLD):
            with self.assertRaises(broker.push_transport.APNSError):
                broker.send_push("ab" * 32, "Rappel", "Message", category="ct_due", reference=f"sandbox-{index}", environment="sandbox")
        sandbox = broker.send_push("ef" * 32, "Rappel", "Message", category="ct_due", reference="sandbox-blocked", environment="sandbox")
        self.assertTrue(sandbox["deferred"])
        with self.assertRaises(broker.push_transport.APNSError):
            broker.send_push("12" * 32, "Rappel", "Message", category="ct_due", reference="production-still-independent", environment="production")
        health = {item["transport"]: item for item in broker.status()["resilience"]["transports"]}
        self.assertTrue(health["push:apns:sandbox"]["circuitOpen"])
        self.assertIn("push:apns:production", health)

    @patch.object(broker.email_transport, "send_email")
    def test_email_retry_after_from_gateway_defers_delivery(self, send_email):
        send_email.side_effect = broker.email_transport.EmailDeliveryError(
            "Gmail rate limited", transport="gmail-api", status=429,
            retry_after="120", retryable=True,
        )
        with self.assertRaises(broker.email_transport.EmailDeliveryError):
            broker.send_email(
                "client@example.fr", "Rappel", "Message",
                category="control_reminder", reference="gmail-rate-limit",
            )
        deferred = broker.send_email(
            "client@example.fr", "Rappel", "Message",
            category="control_reminder", reference="gmail-rate-limit",
        )
        self.assertTrue(deferred["deferred"])
        self.assertGreaterEqual(deferred["retryAfterSeconds"], 119)
        self.assertEqual(send_email.call_count, 1)

    @patch.object(broker.email_transport, "send_email")
    def test_permanent_email_failure_is_not_retried(self, send_email):
        send_email.side_effect = broker.email_transport.EmailDeliveryError(
            "SMTP destinataire refusé (550)", transport="smtp-relay",
            status=550, permanent=True,
        )
        with self.assertRaises(broker.email_transport.EmailDeliveryError):
            broker.send_email(
                "client@example.fr", "Rappel", "Message",
                category="control_reminder", reference="smtp-permanent",
            )
        with self.assertRaises(broker.PermanentDeliverySuppressed):
            broker.send_email(
                "client@example.fr", "Rappel", "Message",
                category="control_reminder", reference="smtp-permanent",
            )
        self.assertEqual(send_email.call_count, 1)
        state = broker.status()
        self.assertEqual(state["failureCounts"]["permanent"], 1)
        self.assertEqual(state["resilience"]["permanentFailures"], 1)

    @patch.object(broker.email_transport, "transport_status", return_value={
        "configured": True, "transport": "gmail-api", "requested": "auto",
        "smtpAvailable": False, "gmailAvailable": True, "state": "ready", "error": "",
    })
    @patch.object(broker.push_transport, "status", return_value={"configured": False, "transport": "apns-http2", "state": "awaiting_credentials"})
    def test_status_exposes_channel_readiness_without_recipient_data(self, push_status, transport_status):
        state = broker.status()
        self.assertTrue(state["channels"]["email"]["configured"])
        self.assertEqual(state["channels"]["email"]["transport"], "gmail-api")
        self.assertFalse(state["channels"]["push"]["configured"])
        self.assertIn("privacy", state)


if __name__ == "__main__":
    unittest.main()
