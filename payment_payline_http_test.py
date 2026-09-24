import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import payment_core as core
import payment_payline_http as routes
import payment_payline_private as private_config


class Handler:
    command = "GET"
    def __init__(self, path):
        self.path = path
        self.response = None
    def send_bytes(self, data, ctype, status=200, cache="no-store", headers=None):
        self.response = {
            "data": data,
            "ctype": ctype,
            "status": status,
            "cache": cache,
            "headers": headers or {},
        }


class PaylineHttpRoutesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name) / "data"
        self.private = Path(self.tmp.name) / "private"
        self.data.mkdir()
        self.private.mkdir()
        self.env = patch.dict(os.environ, {
            "CYBERCHECK_DATA_DIR": str(self.data),
            "CYBERCHECK_PRIVATE_DIR": str(self.private),
        }, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.store = core.SandboxJournal(routes.journal_path())
        quote = core.Quote("appointment-1", "technical", 8000, "b" * 64)
        created = self.store.create(quote, "payline")
        self.intent = self.store.bind_provider(created.payment_id, "TOKEN_FIXTURE_123")

    def verified(self, state="captured"):
        return core.VerifiedEvent(
            self.intent.payment_id, "payline", "TOKEN_FIXTURE_123",
            "payline:TXN_123:00000" if state == "captured" else "payline:TXN_123:01001",
            state, 8000,
        )

    def test_browser_return_rereads_provider_and_applies_verified_event(self):
        handler = Handler("/payment/payline/return?paymentId=" + self.intent.payment_id)
        with patch.object(private_config, "load", return_value=object()),              patch.object(routes.payline, "refresh", return_value=self.verified()) as refresh:
            self.assertTrue(routes.handle(handler))
        self.assertEqual(handler.response["status"], 200)
        self.assertIn(b"Paiement confirm", handler.response["data"])
        self.assertEqual(self.store.get(self.intent.payment_id).state, "captured")
        refresh.assert_called_once()
        self.assertIn("noindex", handler.response["headers"]["X-Robots-Tag"])

    def test_browser_cannot_supply_or_forge_a_success_state(self):
        handler = Handler("/payment/payline/return?paymentId=" + self.intent.payment_id + "&status=captured")
        with patch.object(private_config, "load", return_value=object()),              patch.object(routes.payline, "refresh", side_effect=core.PaymentError("payline_result_not_final")):
            self.assertTrue(routes.handle(handler))
        self.assertEqual(handler.response["status"], 400)
        self.assertEqual(self.store.get(self.intent.payment_id).state, "created")

    def test_cancel_redirect_never_mutates_payment_state(self):
        handler = Handler("/payment/payline/cancel?paymentId=" + self.intent.payment_id + "&status=success")
        with patch.object(routes.payline, "refresh", side_effect=AssertionError("cancel must not call provider")):
            self.assertTrue(routes.handle(handler))
        self.assertEqual(handler.response["status"], 200)
        self.assertEqual(self.store.get(self.intent.payment_id).state, "created")
        self.assertIn(b"interrompu", handler.response["data"])

    def test_notification_token_is_only_a_trigger_for_authenticated_reread(self):
        handler = Handler("/api/payments/payline/notify?notificationType=webtrs&token=TOKEN_FIXTURE_123&status=captured&amount=1")
        with patch.object(private_config, "load", return_value=object()),              patch.object(routes.payline, "refresh", return_value=self.verified()) as refresh:
            self.assertTrue(routes.handle(handler))
        self.assertEqual(handler.response["status"], 204)
        self.assertEqual(self.store.get(self.intent.payment_id).state, "captured")
        refresh.assert_called_once()

    def test_unknown_notification_token_does_not_call_provider(self):
        handler = Handler("/api/payments/payline/notify?notificationType=webtrs&token=UNKNOWN_TOKEN")
        with patch.object(private_config, "load", side_effect=AssertionError("config must not be loaded")),              patch.object(routes.payline, "refresh", side_effect=AssertionError("provider must not be called")):
            self.assertTrue(routes.handle(handler))
        self.assertEqual(handler.response["status"], 404)

    def test_missing_private_configuration_fails_closed(self):
        handler = Handler("/payment/payline/return?paymentId=" + self.intent.payment_id)
        with patch.object(private_config, "load",
                          side_effect=private_config.PaylinePrivateConfigurationError("payline_private_missing")),              patch.object(routes.payline, "refresh", side_effect=AssertionError("provider must not be called")):
            self.assertTrue(routes.handle(handler))
        self.assertEqual(handler.response["status"], 503)
        self.assertEqual(self.store.get(self.intent.payment_id).state, "created")

    def test_non_payline_routes_are_ignored(self):
        handler = Handler("/api/mobile/bootstrap")
        self.assertFalse(routes.handle(handler))
        self.assertIsNone(handler.response)


if __name__ == "__main__":
    unittest.main()
