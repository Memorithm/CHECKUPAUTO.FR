import builtins
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import apns_gateway as apns
import notification_broker as broker


_READY = {"configured": True}
_CONFIG = {
    "keyId": "ABCDEFGHIJ",
    "teamId": "KLMNOPQRST",
    "keyPath": "/nonexistent/test-key.p8",
    "topic": "fr.checkupauto.reminder",
}


class APNsLocalConfigurationBoundaryTest(unittest.TestCase):
    @patch.object(apns, "status", return_value=_READY)
    @patch.object(apns, "_config", return_value=_CONFIG)
    def test_missing_http_runtime_is_typed_configuration_failure(self, config, status):
        real_import = builtins.__import__

        def guarded_import(name, *args, **kwargs):
            if name == "httpx":
                raise ImportError("unavailable")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=guarded_import):
            with self.assertRaises(apns.APNSError) as caught:
                apns.send("ab" * 32, "Rappel", "Message")
        self.assertEqual(caught.exception.reason, "RuntimeDependencyMissing")
        self.assertTrue(caught.exception.provider_error)
        self.assertEqual(broker._classify_failure(caught.exception), "configuration")

    @patch.object(apns, "status", return_value=_READY)
    @patch.object(apns, "_config", return_value=_CONFIG)
    @patch.object(apns, "_provider_token", side_effect=ValueError("bad local key detail"))
    def test_signing_failure_is_bounded_and_typed(self, provider_token, config, status):
        with self.assertRaises(apns.APNSError) as caught:
            apns.send("cd" * 32, "Rappel", "Message")
        self.assertEqual(caught.exception.reason, "SigningKeyInvalid")
        self.assertNotIn("bad local key detail", str(caught.exception))
        self.assertTrue(caught.exception.provider_error)
        self.assertEqual(broker._classify_failure(caught.exception), "configuration")

    @patch.object(broker.push_transport, "send")
    def test_broker_opens_configuration_circuit_for_typed_signing_failure(self, send_push):
        send_push.side_effect = apns.APNSError(0, "SigningKeyInvalid")
        with tempfile.TemporaryDirectory() as tmp:
            old_dir, old_db = broker.DATA_DIR, broker.DB
            broker.DATA_DIR = Path(tmp)
            broker.DB = broker.DATA_DIR / "broker.sqlite3"
            try:
                broker.init_db()
                with self.assertRaises(apns.APNSError):
                    broker.send_push(
                        "ef" * 32,
                        "Rappel",
                        "Message",
                        category="ct_due",
                        reference="apns-signing-config",
                    )
                with broker.connect() as db:
                    delivery = db.execute(
                        "SELECT failure_class,last_error FROM notification_delivery"
                    ).fetchone()
                    health = db.execute(
                        "SELECT configuration_failures,transient_failures,circuit_opens,open_until FROM notification_transport_health"
                    ).fetchone()
                self.assertEqual(delivery["failure_class"], "configuration")
                self.assertIn("reason=SigningKeyInvalid", delivery["last_error"])
                self.assertEqual(health["configuration_failures"], 1)
                self.assertEqual(health["transient_failures"], 0)
                self.assertEqual(health["circuit_opens"], 1)
                self.assertTrue(health["open_until"])
            finally:
                broker.DATA_DIR = old_dir
                broker.DB = old_db


if __name__ == "__main__":
    unittest.main()
