import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import apns_gateway as apns
import notification_broker as broker


class APNSRequestFailureBoundaryTest(unittest.TestCase):
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

    def test_provider_request_reasons_are_non_retryable_request_errors(self):
        for status, reason in (
            (400, "BadPriority"),
            (404, "BadPath"),
            (405, "MethodNotAllowed"),
            (413, "PayloadTooLarge"),
        ):
            with self.subTest(status=status, reason=reason):
                exc = apns.APNSError(status, reason)
                self.assertTrue(exc.request_error)
                self.assertFalse(exc.provider_error)
                self.assertFalse(exc.retryable)
                self.assertFalse(exc.token_invalid)

        idle = apns.APNSError(400, "IdleTimeout")
        self.assertTrue(idle.retryable)
        self.assertFalse(idle.request_error)

    def test_local_request_validation_uses_bounded_apns_errors(self):
        with self.assertRaises(apns.APNSError) as ctx:
            apns._environment_host("qa")
        self.assertEqual(ctx.exception.reason, "EnvironmentInvalid")
        self.assertTrue(ctx.exception.request_error)

        with self.assertRaises(apns.APNSError) as ctx:
            apns._encoded_payload("Titre", "Message", notification_category="bad category")
        self.assertEqual(ctx.exception.reason, "CategoryInvalid")

        with self.assertRaises(apns.APNSError) as ctx:
            apns._encoded_payload("Titre", "Message", data={"bad": object()})
        self.assertEqual(ctx.exception.reason, "PayloadInvalid")

        with self.assertRaises(apns.APNSError) as ctx:
            apns._encoded_payload("Titre", "Message", data={"blob": "x" * 5000})
        self.assertEqual(ctx.exception.reason, "PayloadTooLarge")
        self.assertEqual(ctx.exception.status, 413)

    @patch.object(broker.push_transport, "send")
    def test_broker_records_request_failure_without_backoff_or_transport_circuit(self, send_push):
        send_push.side_effect = apns.APNSError(400, "BadPriority")
        token = "ab" * 32
        with self.assertRaises(apns.APNSError):
            broker.send_push(
                token,
                "Rappel",
                "Message",
                category="ct_due",
                reference="request-fault",
            )

        with broker.connect() as db:
            row = db.execute(
                "SELECT status,failure_class,next_attempt_at,last_error FROM notification_delivery WHERE reference=?",
                ("request-fault",),
            ).fetchone()
            health = db.execute(
                "SELECT * FROM notification_transport_health WHERE transport_key=?",
                ("push:apns:sandbox",),
            ).fetchone()

        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["failure_class"], "request")
        self.assertEqual(row["next_attempt_at"], "")
        self.assertEqual(row["last_error"], "APNSError status=400 reason=BadPriority")
        self.assertIsNone(health)
        state = broker.status()
        self.assertEqual(state["failureCounts"]["request"], 1)
        self.assertEqual(state["counts"]["deferred"], 0)
        self.assertEqual(state["resilience"]["circuitsOpen"], 0)


if __name__ == "__main__":
    unittest.main()
