import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

import payment_core as core
import payment_payline as payline
from payment_payline_config import PaylineSandboxConfig


def config():
    return PaylineSandboxConfig(
        merchant_id="123456",
        access_key="sandbox-secret",
        contract_number="1234567",
        public_origin="https://stage.example.test",
    )


def details_xml(payment_id: str, transaction_id: str, code: str, short_message: str, amount: int = 8000) -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
 xmlns:impl="http://impl.ws.payline.experian.com"
 xmlns:obj="http://obj.ws.payline.experian.com">
 <soapenv:Body>
  <impl:getWebPaymentDetailsResponse>
   <impl:result><obj:code>{code}</obj:code><obj:shortMessage>{short_message}</obj:shortMessage></impl:result>
   <impl:transaction><obj:id>{transaction_id}</obj:id></impl:transaction>
   <impl:payment><obj:amount>{amount}</obj:amount><obj:currency>978</obj:currency></impl:payment>
   <impl:order><obj:ref>{payment_id}</obj:ref><obj:amount>{amount}</obj:amount><obj:currency>978</obj:currency></impl:order>
  </impl:getWebPaymentDetailsResponse>
 </soapenv:Body>
</soapenv:Envelope>""".encode()


class PaymentStateMachineRegressionTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store=core.SandboxJournal(Path(self.tmp.name)/"payments.sqlite3")
        quote=core.Quote("mercure:test-booking","technical",8000,"a"*64)
        created=self.store.create(quote,"payline")
        self.intent=self.store.bind_provider(created.payment_id,"TOKEN_FIXTURE_123")

    def event(self, state: str, tx: str, code: str):
        short={"captured":"ACCEPTED","declined":"REFUSED","pending":"INPROGRESS",
               "cancelled":"CANCELLED","error":"ERROR"}[state]
        return payline.parse_details_response(
            details_xml(self.intent.payment_id,tx,code,short),
            self.store.get(self.intent.payment_id),
            "TOKEN_FIXTURE_123",
        )

    def test_declined_attempt_does_not_reserve_transaction_mapping(self):
        declined=self.event("declined","TXN_DECLINED_1","01001")
        updated=self.store._apply_verified(declined)
        self.assertEqual(updated.state,"declined")
        with self.assertRaisesRegex(core.PaymentError,"^provider_transaction_not_found$"):
            self.store.provider_transaction(self.intent.payment_id)

        captured=self.event("captured","TXN_CAPTURED_2","00000")
        updated=self.store._apply_verified(captured)
        self.assertEqual(updated.state,"captured")
        tx=self.store.provider_transaction(self.intent.payment_id)
        self.assertEqual(tx["transactionId"],"TXN_CAPTURED_2")
        self.assertEqual(tx["capturedAmountCents"],8000)

    def test_pending_then_capture_same_transaction_persists_only_final_capture(self):
        pending=self.event("pending","TXN_PENDING_1","02005")
        updated=self.store._apply_verified(pending)
        self.assertEqual(updated.state,"pending")
        with self.assertRaisesRegex(core.PaymentError,"^provider_transaction_not_found$"):
            self.store.provider_transaction(self.intent.payment_id)

        captured=self.event("captured","TXN_PENDING_1","00000")
        updated=self.store._apply_verified(captured)
        self.assertEqual(updated.state,"captured")
        self.assertEqual(
            self.store.provider_transaction(self.intent.payment_id)["transactionId"],
            "TXN_PENDING_1",
        )

    def test_delayed_decline_after_capture_cannot_erase_or_conflict_with_capture(self):
        captured=self.event("captured","TXN_CAPTURED_1","00000")
        self.store._apply_verified(captured)
        delayed=self.event("declined","TXN_DECLINED_LATE","01001")
        updated=self.store._apply_verified(delayed)
        self.assertEqual(updated.state,"captured")
        tx=self.store.provider_transaction(self.intent.payment_id)
        self.assertEqual(tx["transactionId"],"TXN_CAPTURED_1")

    def test_capture_without_provider_transaction_is_rejected(self):
        event=core.VerifiedEvent(
            self.intent.payment_id,"payline","TOKEN_FIXTURE_123",
            "payline:no-tx:00000","captured",8000,"",
        )
        with self.assertRaisesRegex(core.PaymentError,"^provider_transaction_required$"):
            self.store._apply_verified(event)
        self.assertEqual(self.store.get(self.intent.payment_id).state,"created")

    def test_malformed_provider_transaction_id_is_rejected_not_sanitized(self):
        with self.assertRaisesRegex(core.PaymentError,"^payline_transaction_invalid$"):
            payline.parse_details_response(
                details_xml(self.intent.payment_id,"TXN 123","00000","ACCEPTED"),
                self.intent,
                "TOKEN_FIXTURE_123",
            )

    def test_http_error_is_distinct_from_network_unavailable(self):
        http_error=urllib.error.HTTPError(
            config().webpayment_endpoint,503,"Service Unavailable",{},io.BytesIO(b"")
        )
        opener=type("Opener",(),{"open":lambda self,*args,**kwargs: (_ for _ in ()).throw(http_error)})()
        with patch.object(payline.urllib.request,"build_opener",return_value=opener):
            with self.assertRaisesRegex(core.PaymentError,"^payline_transport_status$"):
                payline._post(config(),b"<xml/>","doWebPayment")


if __name__=="__main__":
    unittest.main()
