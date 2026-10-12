"""Gated Payline production: double lock, environment isolation, journal migration.

All identifiers are synthetic; no request leaves the process.
"""
import json
import os
from pathlib import Path
import sqlite3
import contextlib
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import patch

import customer_booking_payment_verified_reader as reader
import payment_checkout as checkout
import payment_core as core
import payment_payline as payline
import payment_payline_private as private
import payment_checkout_test as checkout_fixtures
from payment_payline_config import PaylineSandboxConfig

LIVE = {private.LIVE_FLAG_ENV: "true"}


def mapping(environment):
    return {"environment": environment, "merchantId": "00000012345678",
            "accessKey": "synthetic-private-key", "contractNumber": "TEST_CONTRACT_01",
            "publicOrigin": "https://stage.example"}


def config(environment):
    return PaylineSandboxConfig.from_mapping(mapping(environment))


def intent(environment):
    return core.Intent("a" * 32, "payline", 1, "2026-10-12T22:00:00+00:00",
                       "TOKEN_FIXTURE_123", "created", environment)


class LiveGateTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.private = Path(tmp.name)
        (self.private / "payments").mkdir()
        env = patch.dict(os.environ, {"CYBERCHECK_PRIVATE_DIR": str(self.private)}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        for name in (private.LIVE_FLAG_ENV, "CYBERCHECK_PAYLINE_CONFIG_PATH",
                     "CYBERCHECK_PAYLINE_PRODUCTION_CONFIG_PATH"):
            os.environ.pop(name, None)

    def write(self, file_name, environment):
        path = self.private / "payments" / file_name
        path.write_text(json.dumps(mapping(environment)), encoding="utf-8")
        path.chmod(0o600)

    def test_production_file_alone_never_opens_live_payments(self):
        self.write("payline-sandbox.json", "sandbox")
        self.write("payline-production.json", "production")
        self.assertEqual(private.active_environment(), "sandbox")
        self.assertEqual(private.load().environment, "sandbox")
        with self.assertRaisesRegex(private.PaylinePrivateConfigurationError, "payline_live_disabled"):
            private.load("production")
        self.assertFalse(private.status()["livePaymentsEnabled"])

    def test_flag_and_production_file_together_open_live_payments(self):
        self.write("payline-production.json", "production")
        with patch.dict(os.environ, LIVE):
            self.assertEqual(private.active_environment(), "production")
            cfg = private.load()
            status = private.status()
        self.assertEqual(cfg.environment, "production")
        self.assertEqual(cfg.webpayment_endpoint, "https://services.payline.com/V4/services/WebPaymentAPI")
        self.assertEqual((status["environment"], status["livePaymentsEnabled"]), ("production", True))
        self.assertNotIn("synthetic-private-key", repr(status))

    def test_flag_without_production_file_fails_closed(self):
        self.write("payline-sandbox.json", "sandbox")
        with patch.dict(os.environ, LIVE):
            with self.assertRaisesRegex(private.PaylinePrivateConfigurationError, "payline_private_missing"):
                private.load()
            self.assertFalse(private.status()["livePaymentsEnabled"])

    def test_only_exact_true_opens_the_gate(self):
        self.write("payline-production.json", "production")
        for value in ("1", "TRUE", "yes", " ", ""):
            with self.subTest(value=value), patch.dict(os.environ, {private.LIVE_FLAG_ENV: value}):
                self.assertEqual(private.active_environment(), "sandbox")
                with self.assertRaises(private.PaylinePrivateConfigurationError):
                    private.load("production")

    def test_files_cannot_be_swapped_between_environments(self):
        self.write("payline-sandbox.json", "production")
        self.write("payline-production.json", "sandbox")
        with self.assertRaisesRegex(private.PaylinePrivateConfigurationError, "environment_mismatch"):
            private.load("sandbox")
        with patch.dict(os.environ, LIVE), \
             self.assertRaisesRegex(private.PaylinePrivateConfigurationError, "environment_mismatch"):
            private.load("production")

    def test_existing_homologation_intent_still_rereads_with_homologation_file(self):
        self.write("payline-sandbox.json", "sandbox")
        self.write("payline-production.json", "production")
        with patch.dict(os.environ, LIVE):
            self.assertEqual(private.load("sandbox").environment, "sandbox")


class TransportIsolationTest(unittest.TestCase):
    def test_redirect_hosts_are_pinned_per_environment(self):
        live = "https://webpayment.payline.com/v2/?token=TOKEN_FIXTURE_123"
        homologation = "https://homologation-webpayment.payline.com/v2/?token=TOKEN_FIXTURE_123"
        self.assertEqual(payline._redirect(live, "production"), live)
        self.assertEqual(payline._redirect(homologation, "sandbox"), homologation)
        for url, environment in ((live, "sandbox"), (homologation, "production"),
                                 ("https://webpayment.payline.com.evil.example/v2/", "production"),
                                 (live, "unknown")):
            with self.subTest(url=url, environment=environment), self.assertRaises(core.PaymentError):
                payline._redirect(url, environment)

    def test_start_parses_production_redirect_only_with_production_config(self):
        xml = (b'<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
               b'<s:Body><r><result><code>00000</code></result><token>TOKEN_FIXTURE_123</token>'
               b'<redirectURL>https://webpayment.payline.com/v2/?token=TOKEN_FIXTURE_123</redirectURL>'
               b'</r></s:Body></s:Envelope>')
        result = payline.start(intent("production"), config("production"), sender=lambda body: xml)
        self.assertEqual((result.environment, result.token), ("production", "TOKEN_FIXTURE_123"))
        with self.assertRaises(core.PaymentError):
            payline.start(intent("sandbox"), config("sandbox"), sender=lambda body: xml)

    def test_intent_and_configuration_environments_must_match(self):
        for i, c in (("production", "sandbox"), ("sandbox", "production")):
            with self.subTest(intent=i, config=c):
                with self.assertRaisesRegex(core.PaymentError, "environment_mismatch"):
                    payline.do_web_payment_xml(intent(i), config(c))
                with self.assertRaisesRegex(core.PaymentError, "environment_mismatch"):
                    payline.refresh(intent(i), config(c), sender=lambda body: self.fail("no network"))
        with self.assertRaisesRegex(core.PaymentError, "environment_mismatch"):
            payline.refund_xml(replace(intent("production"), state="captured"), "TXN_1", 1,
                               config("sandbox"), "SEQ_1")


class JournalProductionTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.root.chmod(0o700)

    def quote(self, reference="mercure:prod-1", amount=1):
        return core.Quote(reference, "technical", amount, "b" * 64)

    def test_only_payline_may_record_production_intents(self):
        store = core.SandboxJournal(self.root / "payments.sqlite3")
        created = store.create(self.quote(), "payline", "production")
        self.assertEqual(store.get(created.payment_id).environment, "production")
        with self.assertRaises(core.PaymentError):
            store.create(self.quote("mercure:prod-2"), "paypal", "production")
        with self.assertRaises(core.PaymentError):
            store.create(self.quote("mercure:prod-3"), "payline", "live")

    def test_same_booking_cannot_switch_environment(self):
        store = core.SandboxJournal(self.root / "payments.sqlite3")
        store.create(self.quote(), "payline", "sandbox")
        with self.assertRaisesRegex(core.PaymentError, "booking_payment_conflict"):
            store.create(self.quote(), "payline", "production")

    def test_legacy_sandbox_only_ledger_is_migrated_without_rewriting_history(self):
        path = self.root / "payments.sqlite3"
        store = core.SandboxJournal(path)
        legacy = store.create(self.quote("mercure:legacy"), "payline")
        with contextlib.closing(sqlite3.connect(path)) as db, db:
            # Recreate the pre-production CHECK constraint exactly as shipped.
            sql = db.execute("SELECT sql FROM sqlite_master WHERE name='payment_intents'").fetchone()[0]
            old = sql.replace("CHECK(environment IN ('sandbox','production'))", "CHECK(environment='sandbox')")
            self.assertNotEqual(old, sql)
            db.executescript("PRAGMA foreign_keys=OFF; PRAGMA writable_schema=ON;")
            db.execute("UPDATE sqlite_master SET sql=? WHERE name='payment_intents'", (old,))
        migrated = core.SandboxJournal(path)
        self.assertEqual(migrated.get(legacy.payment_id).environment, "sandbox")
        live = migrated.create(self.quote("mercure:after-migration"), "payline", "production")
        self.assertEqual(migrated.get(live.payment_id).environment, "production")


class CheckoutProductionTest(unittest.TestCase):
    # Reuse the authoritative booking fixtures without re-running their tests.
    setUp = checkout_fixtures.TrustedPaymentQuoteTest.setUp
    _conversion = checkout_fixtures.TrustedPaymentQuoteTest._conversion
    _acceptance = checkout_fixtures.TrustedPaymentQuoteTest._acceptance

    def test_live_gate_creates_and_starts_a_production_intent(self):
        seen = []

        def starter(intent, cfg):
            seen.append((intent.environment, cfg.environment))
            return payline.StartResult("TOKEN_FIXTURE_LIVE",
                                       "https://webpayment.payline.com/v2/?token=TOKEN_FIXTURE_LIVE",
                                       "production")

        with patch.object(checkout.payline_private, "live_enabled", return_value=True), \
             patch.object(checkout.payline_private, "load", return_value=config("production")) as load:
            started = checkout.start_payline_for_booking(self.external_id, starter=starter)
        load.assert_called_once_with("production")
        self.assertEqual(seen, [("production", "production")])
        self.assertEqual(started["environment"], "production")
        self.assertTrue(started["redirectUrl"].startswith("https://webpayment.payline.com/"))

    def test_without_gate_checkout_stays_in_homologation(self):
        with patch.object(checkout.payline_private, "load", return_value=config("sandbox")) as load:
            started = checkout.start_payline_for_booking(self.external_id, starter=lambda i, c: payline.StartResult(
                "TOKEN_FIXTURE_123", "https://homologation-webpayment.payline.com/v2/?token=TOKEN_FIXTURE_123"))
        load.assert_called_once_with("sandbox")
        self.assertEqual(started["environment"], "sandbox")


class VerifiedReaderProductionTest(unittest.TestCase):
    def test_captured_production_payment_is_reported_paid_with_its_environment(self):
        captured = replace(intent("production"), state="captured", amount_cents=8000)

        class Journal:
            def __init__(self, path):
                pass

            def get(self, ref):
                return captured

            def provider_transaction(self, ref):
                return {"provider": "payline", "transactionId": "TXN_1", "capturedAmountCents": 8000}

        with patch.object(reader.binding, "lookup", return_value={
                "bound": True, "provider": "payline", "paymentRef": "a" * 32}), \
             patch.object(reader, "SandboxJournal", Journal):
            result = reader.read(account_id="acc", request_key="k" * 24, expected_amount_cents=8000)
        self.assertEqual((result["paid"], result["environment"]), (True, "production"))


if __name__ == "__main__":
    unittest.main()
