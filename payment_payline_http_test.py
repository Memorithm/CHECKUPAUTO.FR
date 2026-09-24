import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import payment_core as core
import payment_payline_http as routes
import payment_payline_private as private_config


class Handler:
    def __init__(self, path, *, command="GET", payload=None, origin_ok=True, sec_fetch_site="same-origin"):
        self.path = path
        self.command = command
        self.response = None
        self._origin_ok = origin_ok
        raw = b"" if payload is None else json.dumps(payload).encode("utf-8")
        self.rfile = io.BytesIO(raw)
        self.headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(raw)),
            "Sec-Fetch-Site": sec_fetch_site,
        }
    def _admin_origin_ok(self):
        return self._origin_ok
    def _read_json(self):
        length=int(self.headers.get("Content-Length","0"))
        return json.loads(self.rfile.read(length))
    def send_bytes(self, data, ctype, status=200, cache="no-store", headers=None):
        self.response = {
            "data": data,
            "ctype": ctype,
            "status": status,
            "cache": cache,
            "headers": headers or {},
        }
    def send_json(self, data, status=200, headers=None):
        self.response = {
            "json": data,
            "status": status,
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
            state, 8000, "TXN_123",
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

    def test_browser_return_distinguishes_provider_cancel_and_technical_error(self):
        cases=(
            ("cancelled","Paiement annul"),
            ("error","Paiement non finalis"),
        )
        for state,needle in cases:
            with self.subTest(state=state):
                tmp = tempfile.TemporaryDirectory()
                self.addCleanup(tmp.cleanup)
                data = Path(tmp.name) / "data"
                data.mkdir()
                with patch.dict(os.environ, {"CYBERCHECK_DATA_DIR":str(data)}, clear=False):
                    store=core.SandboxJournal(routes.journal_path())
                    created=store.create(core.Quote("appointment-"+state,"technical",8000,"c"*64),"payline")
                    intent=store.bind_provider(created.payment_id,"TOKEN_"+state.upper())
                    event=core.VerifiedEvent(
                        intent.payment_id,"payline",intent.provider_reference,
                        "payline:"+state+":fixture",state,8000,"",
                    )
                    handler=Handler("/payment/payline/return?paymentId="+intent.payment_id)
                    with patch.object(private_config,"load",return_value=object()), \
                         patch.object(routes.payline,"refresh",return_value=event):
                        self.assertTrue(routes.handle(handler))
                    self.assertEqual(handler.response["status"],200)
                    self.assertIn(needle.encode(),handler.response["data"])
                    self.assertEqual(store.get(intent.payment_id).state,state)

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

    def test_notification_type_accepts_documented_uppercase_WEBTRS(self):
        handler = Handler("/api/payments/payline/notify?notificationType=WEBTRS&token=TOKEN_FIXTURE_123")
        with patch.object(private_config, "load", return_value=object()), \
             patch.object(routes.payline, "refresh", return_value=self.verified()) as refresh:
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



    def test_checkout_page_is_first_party_noindex_and_contains_no_payment_secret(self):
        handler=Handler(routes.CHECKOUT_ROUTE)
        self.assertTrue(routes.handle(handler))
        self.assertEqual(handler.response["status"],200)
        body=handler.response["data"]
        self.assertIn(b"Paiement s",body)
        self.assertIn(b"Payline / Monext",body)
        self.assertIn(b"location.hash",body)
        self.assertNotIn(b"merchantId",body)
        self.assertNotIn(b"accessKey",body)
        self.assertNotIn(b"contractNumber",body)
        self.assertIn("noindex",handler.response["headers"]["X-Robots-Tag"])

    def test_public_start_route_accepts_only_server_bound_browser_identity(self):
        handler=Handler(
            routes.START_ROUTE,
            command="POST",
            payload={"ccid":"ccid-fixture","cct":"cct-fixture"},
        )
        result={
            "paymentId":"a"*32,
            "provider":"payline",
            "environment":"sandbox",
            "state":"created",
            "amountCents":8000,
            "currency":"EUR",
            "redirectUrl":"https://homologation-webpayment.payline.com/webpayment/?token=TOKEN_FIXTURE_123",
            "reused":False,
        }
        with patch.object(routes.checkout,"start_payline_for_browser",return_value=result) as start:
            self.assertTrue(routes.handle(handler))
        self.assertEqual(handler.response["status"],201)
        self.assertTrue(handler.response["json"]["ok"])
        self.assertNotIn("merchantId",json.dumps(handler.response["json"]))
        start.assert_called_once_with("ccid-fixture","cct-fixture")

    def test_public_start_route_rejects_cross_site_and_browser_amount(self):
        cross=Handler(
            routes.START_ROUTE,
            command="POST",
            payload={"ccid":"ccid-fixture","cct":"cct-fixture"},
            sec_fetch_site="cross-site",
        )
        with patch.object(routes.checkout,"start_payline_for_browser") as start:
            self.assertTrue(routes.handle(cross))
        self.assertEqual(cross.response["status"],403)
        start.assert_not_called()

        forged=Handler(
            routes.START_ROUTE,
            command="POST",
            payload={"ccid":"ccid-fixture","cct":"cct-fixture","amountCents":1},
        )
        with patch.object(routes.checkout,"start_payline_for_browser") as start:
            self.assertTrue(routes.handle(forged))
        self.assertEqual(forged.response["status"],400)
        self.assertEqual(forged.response["json"]["error"],"payment_start_payload_invalid")
        start.assert_not_called()

    def test_public_start_route_fails_closed_without_provider_configuration(self):
        handler=Handler(
            routes.START_ROUTE,
            command="POST",
            payload={"ccid":"ccid-fixture","cct":"cct-fixture"},
        )
        with patch.object(
            routes.checkout,
            "start_payline_for_browser",
            side_effect=private_config.PaylinePrivateConfigurationError("payline_private_missing"),
        ):
            self.assertTrue(routes.handle(handler))
        self.assertEqual(handler.response["status"],503)
        self.assertEqual(handler.response["json"]["error"],"payment_provider_not_configured")

    def test_non_payline_routes_are_ignored(self):
        handler = Handler("/api/mobile/bootstrap")
        self.assertFalse(routes.handle(handler))
        self.assertIsNone(handler.response)


if __name__ == "__main__":
    unittest.main()
