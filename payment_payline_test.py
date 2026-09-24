import sqlite3
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import payment_core as core
import payment_payline as payline
import payment_payline_config as payline_config


STAMP = "2026-09-24T12:00:00+00:00"


def config():
    return payline_config.PaylineSandboxConfig.from_mapping({
        "environment": "sandbox",
        "merchantId": "00000012345678",
        "accessKey": "synthetic-fixture-key",
        "contractNumber": "TEST_CONTRACT_01",
        "publicOrigin": "https://stage.example",
    })


def intent(bound=False):
    return core.Intent(
        "a" * 32,
        "payline",
        8000,
        STAMP,
        "TOKEN_FIXTURE_123" if bound else "",
    )


def start_response(code="00000", token="TOKEN_FIXTURE_123",
                   redirect="https://homologation-webpayment.payline.com/webpayment/step1.do?token=TOKEN_FIXTURE_123"):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
 xmlns:impl="http://impl.ws.payline.experian.com">
 <soapenv:Body>
  <impl:doWebPaymentResponse>
   <impl:result><impl:code>{code}</impl:code><impl:shortMessage>ACCEPTED</impl:shortMessage></impl:result>
   <impl:token>{token}</impl:token>
   <impl:redirectURL>{redirect}</impl:redirectURL>
  </impl:doWebPaymentResponse>
 </soapenv:Body>
</soapenv:Envelope>""".encode()


def refund_response(code="00000"):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
 xmlns:impl="http://impl.ws.payline.experian.com"
 xmlns:obj="http://obj.ws.payline.experian.com">
 <soapenv:Body>
  <impl:doRefundResponse>
   <impl:result><obj:code>{code}</obj:code><obj:shortMessage>ACCEPTED</obj:shortMessage></impl:result>
  </impl:doRefundResponse>
 </soapenv:Body>
</soapenv:Envelope>""".encode()


def details_response(code="00000", amount="8000", currency="978", order_ref="a"*32,
                     transaction_id="TXN_123456"):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
 xmlns:impl="http://impl.ws.payline.experian.com"
 xmlns:obj="http://obj.ws.payline.experian.com">
 <soapenv:Body>
  <impl:getWebPaymentDetailsResponse>
   <impl:result><obj:code>{code}</obj:code><obj:shortMessage>ACCEPTED</obj:shortMessage></impl:result>
   <impl:transaction><obj:id>{transaction_id}</obj:id><obj:orderReference>other-field</obj:orderReference></impl:transaction>
   <impl:payment><obj:amount>{amount}</obj:amount><obj:currency>{currency}</obj:currency></impl:payment>
   <impl:order><obj:ref>{order_ref}</obj:ref><obj:amount>{amount}</obj:amount><obj:currency>{currency}</obj:currency></impl:order>
   <impl:buyer><obj:customerId>different-id-that-must-not-confuse-parser</obj:customerId></impl:buyer>
  </impl:getWebPaymentDetailsResponse>
 </soapenv:Body>
</soapenv:Envelope>""".encode()


class PaylineSoapConstructionTest(unittest.TestCase):
    def test_do_web_payment_is_homologation_only_and_contains_no_api_secret(self):
        cfg = config()
        raw = payline.do_web_payment_xml(intent(), cfg)
        self.assertNotIn(cfg.access_key.encode(), raw)
        self.assertNotIn(cfg.merchant_id.encode(), raw)
        root = ET.fromstring(raw)
        values = [str(n.text or "") for n in root.iter()]
        for expected in ("34", "8000", "978", "101", "CPT", cfg.contract_number,
                         "https://stage.example/payment/payline/return?paymentId=" + "a" * 32,
                         "https://stage.example/payment/payline/cancel?paymentId=" + "a" * 32,
                         "https://stage.example/api/payments/payline/notify",
                         "a" * 32, "fr", "SSL"):
            self.assertIn(expected, values)

    def test_get_details_request_contains_only_version_and_bound_token(self):
        raw = payline.get_details_xml("TOKEN_FIXTURE_123")
        values = [str(n.text or "") for n in ET.fromstring(raw).iter()]
        self.assertIn("34", values)
        self.assertIn("TOKEN_FIXTURE_123", values)

    def test_start_response_accepts_only_pinned_homologation_redirect(self):
        result = payline.parse_start_response(start_response())
        self.assertEqual(result.token, "TOKEN_FIXTURE_123")
        self.assertTrue(result.redirect_url.startswith("https://homologation-webpayment.payline.com/"))
        for redirect in (
            "https://evil.invalid/pay",
            "http://homologation-webpayment.payline.com/pay",
            "https://homologation-webpayment.payline.com.evil.invalid/pay",
        ):
            with self.subTest(redirect=redirect), self.assertRaises(core.PaymentError):
                payline.parse_start_response(start_response(redirect=redirect))

    def test_non_success_start_result_is_not_redirected(self):
        with self.assertRaisesRegex(core.PaymentError, "^payline_start_refused$"):
            payline.parse_start_response(start_response(code="02101"))


class PaylineVerificationTest(unittest.TestCase):
    def test_final_result_binds_token_amount_currency_and_order_reference(self):
        event = payline.parse_details_response(details_response(), intent(bound=True), "TOKEN_FIXTURE_123")
        self.assertEqual(event.provider, "payline")
        self.assertEqual(event.state, "captured")
        self.assertEqual(event.amount_cents, 8000)
        self.assertEqual(event.provider_reference, "TOKEN_FIXTURE_123")

    def test_final_result_preserves_payline_transaction_identifier(self):
        event = payline.parse_details_response(details_response(), intent(bound=True), "TOKEN_FIXTURE_123")
        self.assertEqual(event.provider_transaction_id, "TXN_123456")

    def test_declined_and_pending_results_remain_distinct(self):
        for code, expected in (("01001", "declined"), ("04012", "declined"), ("02319", "declined"), ("02005", "pending")):
            with self.subTest(code=code):
                event = payline.parse_details_response(details_response(code=code), intent(bound=True), "TOKEN_FIXTURE_123")
                self.assertEqual(event.state, expected)

    def test_unknown_or_technical_result_is_not_persistable(self):
        for code in ("02101", "99999", ""):
            with self.subTest(code=code), self.assertRaises(core.PaymentError):
                payline.parse_details_response(details_response(code=code), intent(bound=True), "TOKEN_FIXTURE_123")

    def test_response_cannot_override_trusted_payment_binding(self):
        cases = [
            {"amount": "1"},
            {"currency": "840"},
            {"order_ref": "b" * 32},
        ]
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(core.PaymentError):
                payline.parse_details_response(details_response(**changes), intent(bound=True), "TOKEN_FIXTURE_123")
        with self.assertRaises(core.PaymentError):
            payline.parse_details_response(details_response(), intent(bound=True), "OTHER_TOKEN")

    def test_xml_entities_and_oversized_responses_are_refused(self):
        with self.assertRaises(core.PaymentError):
            payline.parse_start_response(b'<!DOCTYPE x [<!ENTITY e "x">]><x>&e;</x>')
        with self.assertRaises(core.PaymentError):
            payline.parse_start_response(b"x" * (payline.MAX_RESPONSE_BYTES + 1))

    def test_injected_sender_makes_transport_testable_without_network(self):
        seen = []
        result = payline.start(intent(), config(), sender=lambda body: (seen.append(body), start_response())[1])
        self.assertEqual(result.token, "TOKEN_FIXTURE_123")
        self.assertEqual(len(seen), 1)
        event = payline.refresh(intent(bound=True), config(), sender=lambda body: details_response())
        self.assertEqual(event.state, "captured")


class PaylineRefundFoundationTest(unittest.TestCase):
    def captured_intent(self):
        return core.Intent(
            "a"*32,"payline",8000,STAMP,"TOKEN_FIXTURE_123","sandbox","EUR","captured"
        )

    def test_refund_request_uses_direct_payment_contract_and_idempotency_sequence(self):
        cfg=config()
        raw=payline.refund_xml(
            self.captured_intent(),"TXN_123456",3000,cfg,"refund_a_001","Client request",
        )
        self.assertNotIn(cfg.access_key.encode(),raw)
        self.assertNotIn(cfg.merchant_id.encode(),raw)
        root=ET.fromstring(raw)
        values=[str(n.text or "") for n in root.iter()]
        for expected in ("34","TXN_123456","3000","978","421","CPT",
                         cfg.contract_number,"refund_a_001","Client request"):
            self.assertIn(expected,values)

    def test_refund_never_exceeds_captured_amount_or_runs_on_uncaptured_intent(self):
        with self.assertRaisesRegex(core.PaymentError,"^refund_amount_exceeds_capture$"):
            payline.refund_xml(self.captured_intent(),"TXN_123456",8001,config(),"refund_a_002")
        with self.assertRaisesRegex(core.PaymentError,"^captured_payment_required$"):
            payline.refund_xml(intent(bound=True),"TXN_123456",1000,config(),"refund_a_003")

    def test_refund_result_requires_provider_acceptance(self):
        self.assertEqual(payline.parse_refund_response(refund_response()).result_code,"00000")
        with self.assertRaisesRegex(core.PaymentError,"^payline_refund_refused$"):
            payline.parse_refund_response(refund_response("02101"))

    def test_refund_sender_is_injectable_and_direct_endpoint_is_pinned(self):
        seen=[]
        result=payline.refund(
            self.captured_intent(),"TXN_123456",1000,config(),"refund_a_004",
            sender=lambda body:(seen.append(body),refund_response())[1],
        )
        self.assertEqual(result.result_code,"00000")
        self.assertEqual(len(seen),1)
        self.assertEqual(
            config().directpayment_endpoint,
            "https://homologation.payline.com/V4/services/DirectPaymentAPI",
        )


class PaylineJournalMigrationTest(unittest.TestCase):
    def test_existing_paypal_monetico_database_migrates_without_history_loss(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "payments.sqlite3"
            with sqlite3.connect(path) as db:
                db.executescript("""
                CREATE TABLE payment_intents(
                  payment_id TEXT PRIMARY KEY,
                  booking_hash TEXT NOT NULL UNIQUE,
                  quote_hash TEXT NOT NULL,
                  provider TEXT NOT NULL CHECK(provider IN ('paypal','monetico')),
                  environment TEXT NOT NULL CHECK(environment='sandbox'),
                  amount_cents INTEGER NOT NULL,
                  currency TEXT NOT NULL CHECK(currency='EUR'),
                  provider_reference TEXT NOT NULL DEFAULT '',
                  state TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX payment_provider_reference
                  ON payment_intents(provider,provider_reference) WHERE provider_reference<>'';
                CREATE TABLE payment_events(
                  provider TEXT NOT NULL,
                  event_hash TEXT NOT NULL,
                  payment_id TEXT NOT NULL REFERENCES payment_intents(payment_id),
                  evidence_hash TEXT NOT NULL,
                  state TEXT NOT NULL,
                  received_at TEXT NOT NULL,
                  PRIMARY KEY(provider,event_hash)
                );
                """)
                db.execute("INSERT INTO payment_intents VALUES(?,?,?,?,?,?,?,?,?,?)", (
                    "1"*32, "booking", "quote", "paypal", "sandbox", 8000, "EUR",
                    "ORDER_1", "captured", STAMP,
                ))
                db.execute("INSERT INTO payment_events VALUES(?,?,?,?,?,?)", (
                    "paypal", "event", "1"*32, "evidence", "captured", STAMP,
                ))
            path.chmod(0o600)
            store = core.SandboxJournal(path)
            existing = store.get("1"*32)
            self.assertEqual(existing.provider, "paypal")
            created = store.create(core.Quote("booking-2", "technical", 8000, "b"*64), "payline")
            self.assertEqual(created.provider, "payline")
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM payment_events").fetchone()[0], 1)
                self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_payline_verified_event_persists_transaction_idempotently(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"payments.sqlite3"
            store=core.SandboxJournal(path)
            created=store.create(core.Quote("booking-tx","technical",8000,"d"*64),"payline")
            bound=store.bind_provider(created.payment_id,"TOKEN_FIXTURE_123")
            event=payline.parse_details_response(
                details_response(order_ref=created.payment_id,transaction_id="TXN_ABC123"),
                bound,"TOKEN_FIXTURE_123",
            )
            store._apply_verified(event)
            store._apply_verified(event)
            tx=store.provider_transaction(created.payment_id)
            self.assertEqual(tx["provider"],"payline")
            self.assertEqual(tx["transactionId"],"TXN_ABC123")
            self.assertEqual(tx["capturedAmountCents"],8000)
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM payment_provider_transactions").fetchone()[0],1)

    def test_payline_verified_event_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "payments.sqlite3"
            store = core.SandboxJournal(path)
            created = store.create(core.Quote("booking-3", "technical", 8000, "c"*64), "payline")
            bound = store.bind_provider(created.payment_id, "TOKEN_FIXTURE_123")
            event = payline.parse_details_response(
                details_response(order_ref=created.payment_id),
                bound,
                "TOKEN_FIXTURE_123",
            )
            first = store._apply_verified(event)
            second = store._apply_verified(event)
            self.assertEqual(first.state, "captured")
            self.assertEqual(second.state, "captured")
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM payment_events").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
