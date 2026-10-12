"""HTTP contract: booking written to Mercure first, then the Payline step."""
import contextlib
import unittest
from unittest.mock import Mock, patch

import customer_http as http
from customer_booking_http_contract_test import Handler

ACCOUNT = {"accountId": "00000000-0000-4000-8000-000000000001"}
KEY = "booking-payment-http-key-0001"
PAYLOAD = {"service": "technical", "date": "2026-10-15", "time": "10:30",
           "vehicleId": "owned-vehicle", "requestKey": KEY}


class Base(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(http, "_account", return_value=("token", ACCOUNT)))
        self.stack.enter_context(patch.object(http, "_same_origin", return_value=True))
        self.csrf = self.stack.enter_context(
            patch.object(http.customer_accounts, "verify_csrf", return_value=True))

    def call(self, path, payload):
        handler = Handler(payload)
        handler.path = path
        self.assertTrue(http.handle(handler))
        return handler.response


class CreateThenPaymentTests(Base):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.object(http.customer_accounts, "list_vehicles",
                                              return_value=[{"vehicleId": "owned-vehicle"}]))
        self.stack.enter_context(patch.object(http.customer_booking_server_config_source, "load",
                                              return_value={"enabled": True}))
        self.stack.enter_context(patch.object(http.customer_booking_http_trusted_context, "prepare",
                                              return_value=(Mock(), {})))
        self.created = {"ok": True, "confirmed": True, "state": "confirmed",
                        "paymentDue": "after_booking", "service": "technical", "priceCents": 8000}

    def test_confirmed_booking_binds_intent_with_server_price_and_hides_basis(self):
        with patch.object(http.customer_booking_create_api, "create", return_value=self.created) as create, \
             patch.object(http.customer_booking_payment_start, "record_confirmed_booking") as record:
            response = self.call("/api/customer/booking/create", PAYLOAD | {"ccid": "intent", "cct": "signed"})
        self.assertEqual(response["status"], 200)
        self.assertEqual(create.call_args.args[0], PAYLOAD)
        record.assert_called_once_with(account_id=ACCOUNT["accountId"], request_key=KEY, ccid="intent",
                                       cct="signed", service="technical", price_cents=8000)
        self.assertEqual(response["json"], {"ok": True, "confirmed": True, "state": "confirmed",
                                            "paymentDue": "after_booking", "paymentReady": True})

    def test_binding_failure_keeps_the_booking_response(self):
        with patch.object(http.customer_booking_create_api, "create", return_value=self.created), \
             patch.object(http.customer_booking_payment_start, "record_confirmed_booking",
                          side_effect=ValueError("payment_browser_token_invalid")):
            response = self.call("/api/customer/booking/create", PAYLOAD | {"ccid": "intent", "cct": "bad"})
        self.assertEqual(response["status"], 200)
        self.assertTrue(response["json"]["confirmed"])
        self.assertFalse(response["json"]["paymentReady"])

    def test_pending_booking_is_never_bound(self):
        with patch.object(http.customer_booking_create_api, "create",
                          return_value={"ok": True, "confirmed": False, "state": "reconciliation_required"}), \
             patch.object(http.customer_booking_payment_start, "record_confirmed_booking") as record:
            response = self.call("/api/customer/booking/create", PAYLOAD | {"ccid": "intent", "cct": "signed"})
        record.assert_not_called()
        self.assertNotIn("paymentReady", response["json"])

    def test_partial_or_non_string_intent_is_rejected_before_any_write(self):
        for extra in ({"ccid": "intent"}, {"ccid": 1, "cct": "signed"}):
            with self.subTest(extra=extra), \
                 patch.object(http.customer_booking_create_api, "create") as create:
                response = self.call("/api/customer/booking/create", PAYLOAD | extra)
            self.assertEqual(response["status"], 422)
            create.assert_not_called()


class PaymentStartRouteTests(Base):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.object(http.site_config_store, "load", return_value={}))

    def test_starts_payment_for_request_key_only(self):
        result = {"ok": True, "paid": False, "redirectUrl": "https://homologation.payline.com/x",
                  "amountCents": 8000}
        with patch.object(http.customer_booking_payment_start, "start", return_value=result) as start:
            response = self.call("/api/customer/booking/payment/start", {"requestKey": KEY})
        start.assert_called_once_with(account_id=ACCOUNT["accountId"], request_key=KEY)
        self.assertEqual((response["status"], response["json"]), (200, result))

    def test_browser_cannot_supply_amount_or_reference(self):
        with patch.object(http.customer_booking_payment_start, "start") as start:
            response = self.call("/api/customer/booking/payment/start",
                                 {"requestKey": KEY, "amountCents": 1})
        self.assertEqual(response["status"], 400)
        start.assert_not_called()

    def test_csrf_and_delegated_mode_block_payment(self):
        self.csrf.return_value = False
        with patch.object(http.customer_booking_payment_start, "start") as start:
            self.assertEqual(self.call("/api/customer/booking/payment/start", {"requestKey": KEY})["status"], 403)
        self.csrf.return_value = True
        with patch.object(http.payment_mode, "status", return_value={"delegated": True}), \
             patch.object(http.customer_booking_payment_start, "start") as start:
            self.assertEqual(self.call("/api/customer/booking/payment/start", {"requestKey": KEY})["status"], 409)
        start.assert_not_called()

    def test_refusal_and_outage_codes(self):
        err = http.customer_booking_payment_start.BookingPaymentStartError("booking_not_confirmed")
        with patch.object(http.customer_booking_payment_start, "start", side_effect=err):
            response = self.call("/api/customer/booking/payment/start", {"requestKey": KEY})
        self.assertEqual((response["status"], response["json"]["error"]), (409, "booking_not_confirmed"))
        with patch.object(http.customer_booking_payment_start, "start", side_effect=RuntimeError("down")):
            response = self.call("/api/customer/booking/payment/start", {"requestKey": KEY})
        self.assertEqual((response["status"], response["json"]["error"]),
                         (503, "booking_payment_start_unavailable"))


if __name__ == "__main__":
    unittest.main()
