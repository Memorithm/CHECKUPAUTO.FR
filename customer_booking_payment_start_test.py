"""Booking first, then Payline: server-side authority for the payment step."""
import unittest
from unittest.mock import patch

import customer_booking_payment_start as start
from payment_core import PaymentError

ACCOUNT = "00000000-0000-4000-8000-000000000001"
KEY = "booking-payment-start-key-0001"
CONFIRMED = {"state": "confirmed", "confirmed": True, "providerReference": "rdv-4242"}


class RecordConfirmedBookingTests(unittest.TestCase):
    def kwargs(self, **extra):
        return {"account_id": ACCOUNT, "request_key": KEY, "ccid": "intent-token",
                "cct": "signed", "service": "technical", "price_cents": 8000} | extra

    def test_server_basis_and_mercure_reference_feed_the_conversion(self):
        with patch.object(start.booking, "verify_browser_token", return_value=True), \
             patch.object(start.journal, "status", return_value=CONFIRMED), \
             patch.object(start.booking, "apply_conversion",
                          return_value={"contractAcceptanceBound": True}) as convert:
            result = start.record_confirmed_booking(**self.kwargs())
        self.assertEqual(result, {"recorded": True, "contractAcceptanceBound": True})
        payload = convert.call_args.args[0]
        self.assertEqual((payload["externalId"], payload["status"], payload["ccid"], payload["amount"]),
                         ("rdv-4242", "confirmed", "intent-token", 80.0))
        self.assertEqual(payload["service"], "Contrôle technique")

    def test_invalid_token_basis_or_unconfirmed_booking_never_records(self):
        cases = (
            (False, self.kwargs(), CONFIRMED, "payment_browser_token_invalid"),
            (True, self.kwargs(service="pollution"), CONFIRMED, "payment_basis_invalid"),
            (True, self.kwargs(price_cents=9001), CONFIRMED, "payment_basis_invalid"),
            (True, self.kwargs(price_cents="8000"), CONFIRMED, "payment_basis_invalid"),
            (True, self.kwargs(), {"state": "reconciliation_required", "confirmed": False,
                                   "providerReference": ""}, "booking_not_confirmed"),
        )
        for token_ok, kwargs, state, code in cases:
            with self.subTest(code=code, kwargs=kwargs), \
                 patch.object(start.booking, "verify_browser_token", return_value=token_ok), \
                 patch.object(start.journal, "status", return_value=state), \
                 patch.object(start.booking, "apply_conversion") as convert:
                with self.assertRaisesRegex(start.BookingPaymentStartError, code):
                    start.record_confirmed_booking(**kwargs)
                convert.assert_not_called()


class StartTests(unittest.TestCase):
    def test_starts_payline_for_the_confirmed_booking_and_binds_it(self):
        started = {"paymentId": "a" * 32, "redirectUrl": "https://homologation.payline.com/x",
                   "amountCents": 8000}
        with patch.object(start.journal, "status", return_value=CONFIRMED), \
             patch.object(start.payment_status, "status", return_value={"payment": {"paid": False}}), \
             patch.object(start.payment_checkout, "start_payline_for_booking", return_value=started) as pay, \
             patch.object(start.binding, "bind") as bind:
            result = start.start(account_id=ACCOUNT, request_key=KEY)
        pay.assert_called_once_with("rdv-4242", starter=None)
        bind.assert_called_once_with(account_id=ACCOUNT, request_key=KEY, provider_booking_ref="rdv-4242",
                                     payment_ref="a" * 32, payment_provider="payline", authorized=True)
        self.assertEqual(result, {"ok": True, "paid": False, "redirectUrl": started["redirectUrl"],
                                  "amountCents": 8000})

    def test_paid_booking_is_not_sent_to_payline_again(self):
        with patch.object(start.journal, "status", return_value=CONFIRMED), \
             patch.object(start.payment_status, "status", return_value={"payment": {"paid": True}}), \
             patch.object(start.payment_checkout, "start_payline_for_booking") as pay:
            self.assertEqual(start.start(account_id=ACCOUNT, request_key=KEY), {"ok": True, "paid": True})
        pay.assert_not_called()

    def test_unknown_or_unconfirmed_booking_cannot_start_payment(self):
        for state, code in ((start.journal.BookingJournalError("booking_request_not_found"), "booking_not_found"),
                            ({"state": "prepared", "confirmed": False, "providerReference": ""},
                             "booking_not_confirmed")):
            kwargs = {"side_effect": state} if isinstance(state, Exception) else {"return_value": state}
            with self.subTest(code=code), patch.object(start.journal, "status", **kwargs), \
                 patch.object(start.payment_checkout, "start_payline_for_booking") as pay:
                with self.assertRaisesRegex(start.BookingPaymentStartError, code):
                    start.start(account_id=ACCOUNT, request_key=KEY)
                pay.assert_not_called()

    def test_payment_errors_are_reported_without_binding(self):
        with patch.object(start.journal, "status", return_value=CONFIRMED), \
             patch.object(start.payment_status, "status", return_value={"payment": {"paid": False}}), \
             patch.object(start.payment_checkout, "start_payline_for_booking",
                          side_effect=PaymentError("contract_acceptance_required")), \
             patch.object(start.binding, "bind") as bind:
            with self.assertRaisesRegex(start.BookingPaymentStartError, "contract_acceptance_required"):
                start.start(account_id=ACCOUNT, request_key=KEY)
        bind.assert_not_called()


if __name__ == "__main__":
    unittest.main()
