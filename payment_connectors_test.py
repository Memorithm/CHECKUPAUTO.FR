import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

import payment_core as core
import payment_monetico as bank
import payment_paypal as paypal

STAMP = "2026-09-22T12:00:00+00:00"
MERCHANT = "MERCHANT12345"
ORDER = "ORDER1234567890"
CAPTURE = "CAPTURE12345678"
TEST_KEY = "0011223344556677889900112233445566778899"


def intent(provider="paypal", bound=True):
    return core.Intent("a" * 32, provider, 8000, STAMP,
                       (ORDER if provider == "paypal" else "a" * 32) if bound else "")


def config():
    return paypal.PayPalSandboxConfig("sandbox_client_fixture", "sandbox_secret_fixture",
                                     MERCHANT, "https://demo.example", "WH-FIXTURE")


def bank_config():
    return bank.MoneticoSandboxConfig("1234567", "demo", TEST_KEY, "https://demo.example")


def captured():
    return {"id": ORDER, "status": "COMPLETED", "purchase_units": [{
        "reference_id": "a" * 32, "custom_id": "a" * 32,
        "amount": {"currency_code": "EUR", "value": "80.00"},
        "payee": {"merchant_id": MERCHANT},
        "payments": {"captures": [{"id": CAPTURE, "status": "COMPLETED",
            "final_capture": True, "amount": {"currency_code": "EUR", "value": "80.00"}}]},
    }], "payer": {"email_address": "synthetic@example.invalid"}}


def notification(code="payetest", **changes):
    fields = {"TPE": "1234567", "reference": "a" * 32, "date": "22/09/2026_a_14:00:00",
              "montant": "80.00EUR", "code-retour": code, "numauto": "AUTH123",
              "cbmasquee": "12345678******90", "future-field": "signed"}
    fields.update(changes)
    fields["MAC"] = bank.mac(fields, TEST_KEY)
    return urlencode(fields).encode()


class MoneyAndConfigurationTest(unittest.TestCase):
    def test_money_never_uses_float_or_silent_rounding(self):
        for value in (True, False, 80.0, "8000", 0, -1, 9001):
            with self.subTest(value=value), self.assertRaises(core.PaymentError):
                core.cents(value)
        for value in ("8e1", "80.001", "NaN", "80,00", " 80.00", "-1", 80, True):
            with self.subTest(value=value), self.assertRaises(core.PaymentError):
                core.parse_eur(value)
        self.assertEqual(core.parse_eur("80.0"), 8000)
        self.assertEqual(core.decimal_amount(1), "0.01")

    def test_only_authorized_service_ranges(self):
        core.Quote("appointment-1", "technical", 7200, "b" * 64)
        core.Quote("appointment-1", "fitted", 9000, "b" * 64)
        for service, amount in (("technical", 8001), ("pollution", 3000), ("fitted", 0)):
            with self.subTest(service=service), self.assertRaises(core.PaymentError):
                core.Quote("appointment-1", service, amount, "b" * 64)

    def test_live_environment_is_refused(self):
        with self.assertRaises(core.PaymentError):
            replace(intent(), environment="live")
        readiness = core.capability()
        for field in ("livePaymentsEnabled", "checkoutBound", "httpCallbacksBound", "refundsBound"):
            self.assertIs(readiness[field], False)

    def test_secrets_do_not_appear_in_config_repr(self):
        self.assertNotIn(config().client_secret, repr(config()))
        self.assertNotIn(config().client_id, repr(config()))
        self.assertNotIn(TEST_KEY, repr(bank_config()))

    def test_origin_validation(self):
        for value in ("http://demo.example", "https://user:pass@demo.example", "https://demo.example/a",
                      "https://demo.example?x=1", "https://demo.example/#frag", "https://demo.example:8080", "https://demo.example\n"):
            with self.subTest(value=value), self.assertRaises(core.PaymentError):
                paypal.origin_url(value)

    def test_strict_json_rejects_duplicates_and_oversized_bodies(self):
        for raw in (b'{"status":"APPROVED","status":"COMPLETED"}', b'{"x":NaN}', b'[]', b' ' * (paypal.MAX_BODY + 1)):
            with self.subTest(raw=raw[:40]), self.assertRaises(core.PaymentError):
                paypal.strict_json(raw)


class PayPalConnectorTest(unittest.TestCase):
    def test_create_payload_is_server_amount_without_payer_or_card_data(self):
        data = paypal.create_order_payload(intent(), config())
        self.assertEqual(data["purchase_units"][0]["amount"], {"value": "80.00", "currency_code": "EUR"})
        self.assertEqual(data["purchase_units"][0]["payee"]["merchant_id"], MERCHANT)
        self.assertEqual(data["payment_source"]["paypal"]["experience_context"]["shipping_preference"], "NO_SHIPPING")
        self.assertNotIn("card", json.dumps(data))

    def test_retry_ids_are_stable_and_action_specific(self):
        self.assertEqual(paypal.request_id(intent(), "create"), paypal.request_id(intent(), "create"))
        self.assertNotEqual(paypal.request_id(intent(), "capture"), paypal.request_id(intent(), "create"))
        self.assertEqual(len(paypal.request_id(intent(), "capture")), 32)

    def test_verified_capture_is_minimized(self):
        event = paypal.capture_evidence(captured(), intent(), MERCHANT)
        self.assertEqual(event.state, "captured")
        self.assertEqual(event.event_id, "capture:" + CAPTURE)
        self.assertNotIn("synthetic@example.invalid", repr(event))

    def test_approval_and_pending_are_not_capture(self):
        for status in ("APPROVED", "PENDING", "CREATED"):
            data = captured(); data["status"] = status
            with self.subTest(status=status), self.assertRaises(core.PaymentError):
                paypal.capture_evidence(data, intent(), MERCHANT)
        for status in ("PENDING", "DECLINED", "REFUNDED", "PARTIALLY_REFUNDED", "FAILED"):
            data = captured(); data["purchase_units"][0]["payments"]["captures"][0]["status"] = status
            with self.subTest(status=status), self.assertRaises(core.PaymentError):
                paypal.capture_evidence(data, intent(), MERCHANT)

    def test_capture_checks_order_reference_payee_currency_and_amount(self):
        for field, value in (("reference_id", "b" * 32), ("custom_id", "b" * 32),
                             ("payee", {"merchant_id": "OTHER12345678"}),
                             ("amount", {"value": "79.99", "currency_code": "EUR"}),
                             ("amount", {"value": "80.00", "currency_code": "USD"})):
            data = captured(); data["purchase_units"][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(core.PaymentError):
                paypal.capture_evidence(data, intent(), MERCHANT)
        with self.assertRaises(core.PaymentError):
            paypal.capture_evidence(captured(), replace(intent(), provider_reference="OTHERORDER99"), MERCHANT)

    def test_capture_refuses_multiple_or_partial_captures(self):
        data = captured(); data["purchase_units"][0]["payments"]["captures"] *= 2
        with self.assertRaises(core.PaymentError):
            paypal.capture_evidence(data, intent(), MERCHANT)
        data = captured(); data["purchase_units"][0]["payments"]["captures"][0]["final_capture"] = False
        with self.assertRaises(core.PaymentError):
            paypal.capture_evidence(data, intent(), MERCHANT)

    def test_create_returns_only_sandbox_approval_not_paid(self):
        client = paypal.SandboxPayPal(config())
        response = {"id": ORDER, "status": "PAYER_ACTION_REQUIRED", "links": [{"rel": "payer-action", "href": "https://www.sandbox.paypal.com/checkoutnow?token=" + ORDER}]}
        with patch.object(client, "_api", return_value=response) as api:
            result = client.create_order(intent(bound=False))
        self.assertIs(result["paid"], False)
        self.assertEqual(result["orderId"], ORDER)
        self.assertEqual(api.call_args.args[1], "/v2/checkout/orders")

    def test_non_sandbox_or_foreign_approval_is_refused(self):
        client = paypal.SandboxPayPal(config())
        for url in ("https://www.paypal.com/checkoutnow?token=" + ORDER,
                    "https://www.sandbox.paypal.com.evil.invalid/checkoutnow?token=" + ORDER,
                    "https://www.sandbox.paypal.com/checkoutnow?token=OTHERORDER"):
            response = {"id": ORDER, "status": "CREATED", "links": [{"rel": "approve", "href": url}]}
            with self.subTest(url=url), patch.object(client, "_api", return_value=response), self.assertRaises(core.PaymentError):
                client.create_order(intent(bound=False))

    def test_transport_does_not_follow_redirect_or_echo_body(self):
        client = paypal.SandboxPayPal(config())
        with patch.object(paypal.http.client, "HTTPSConnection") as connection:
            response = connection.return_value.getresponse.return_value
            response.status = 302; response.read.return_value = b'private-provider-body'
            with self.assertRaisesRegex(core.PaymentError, "^paypal_request_failed$"):
                client._request("POST", "/v1/oauth2/token", {}, b"")
            self.assertEqual(connection.call_args.args[0], paypal.API_HOST)
            connection.return_value.close.assert_called_once()

    def test_capture_requires_persisted_order_binding(self):
        with self.assertRaises(core.PaymentError):
            paypal.SandboxPayPal(config()).capture_order(intent(bound=False))

    def test_existing_order_is_not_created_or_captured_again(self):
        client = paypal.SandboxPayPal(config())
        with patch.object(client, "_api") as api:
            with self.assertRaises(core.PaymentError):
                client.create_order(intent())
            with self.assertRaises(core.PaymentError):
                client.capture_order(replace(intent(), state="captured"))
        api.assert_not_called()

    def test_oauth_and_capture_request_preserve_idempotency_header(self):
        client = paypal.SandboxPayPal(config())
        with patch.object(client, "_request", side_effect=[
            {"access_token": "fixture_access_token", "token_type": "Bearer"}, captured()
        ]) as transport:
            result = client.capture_order(intent())
        self.assertEqual(result.state, "captured")
        self.assertEqual(transport.call_args_list[0].args[1], "/v1/oauth2/token")
        self.assertEqual(transport.call_args_list[1].args[2]["PayPal-Request-ID"], paypal.request_id(intent(), "capture"))
        self.assertEqual(transport.call_args_list[1].args[2]["Prefer"], "return=representation")

    def webhook_input(self):
        event = {"event_type": "PAYMENT.CAPTURE.COMPLETED", "resource": {"id": CAPTURE,
                 "supplementary_data": {"related_ids": {"order_id": ORDER}}}}
        headers = {"PAYPAL-AUTH-ALGO": "SHA256withRSA", "PAYPAL-CERT-URL": "https://api.sandbox.paypal.com/v1/notifications/certs/CERT-FIXTURE",
                   "PAYPAL-TRANSMISSION-ID": "TX-FIXTURE", "PAYPAL-TRANSMISSION-TIME": STAMP, "PAYPAL-TRANSMISSION-SIG": "synthetic-signature"}
        return json.dumps(event).encode(), headers

    def test_webhook_requires_signature_success_then_fresh_order_read(self):
        raw, headers = self.webhook_input(); client = paypal.SandboxPayPal(config())
        with patch.object(client, "_api", side_effect=[{"verification_status": "SUCCESS"}, captured()]) as api:
            event = client.verify_webhook(intent(), raw, headers)
        self.assertEqual(event.event_id, "capture:" + CAPTURE)
        self.assertEqual(api.call_args_list[0].args[1], "/v1/notifications/verify-webhook-signature")
        self.assertEqual(api.call_args_list[0].args[2]["webhook_id"], "WH-FIXTURE")
        self.assertEqual(api.call_args_list[1].args, ("GET", "/v2/checkout/orders/" + ORDER))

    def test_bad_signature_never_reads_order(self):
        raw, headers = self.webhook_input(); client = paypal.SandboxPayPal(config())
        with patch.object(client, "_api", return_value={"verification_status": "FAILURE"}) as api:
            with self.assertRaises(core.PaymentError):
                client.verify_webhook(intent(), raw, headers)
        self.assertEqual(api.call_count, 1)

    def test_webhook_certificate_cannot_point_to_arbitrary_host(self):
        raw, headers = self.webhook_input(); client = paypal.SandboxPayPal(config())
        headers["PAYPAL-CERT-URL"] = "https://127.0.0.1/private"
        with patch.object(client, "_api") as api, self.assertRaises(core.PaymentError):
            client.verify_webhook(intent(), raw, headers)
        api.assert_not_called()

    def test_webhook_header_duplicates_and_malformed_certificate_are_refused(self):
        client = paypal.SandboxPayPal(config())
        raw, headers = self.webhook_input()
        duplicate = {**headers, "paypal-auth-algo": "SHA256withRSA"}
        malformed = {**headers, "PAYPAL-CERT-URL": "https://[invalid"}
        for current in (duplicate, malformed):
            with self.subTest(headers=current), patch.object(client, "_api") as api, self.assertRaises(core.PaymentError):
                client.verify_webhook(intent(), raw, current)
            api.assert_not_called()

    def test_unbound_webhook_never_performs_network_call(self):
        raw, headers = self.webhook_input(); client = paypal.SandboxPayPal(config())
        with patch.object(client, "_api") as api, self.assertRaises(core.PaymentError):
            client.verify_webhook(intent(bound=False), raw, headers)
        api.assert_not_called()


class MoneticoConnectorTest(unittest.TestCase):
    def test_mac_matches_independent_openssl_vector_with_utf8(self):
        fields = {"montant": "80.00EUR", "TPE": "1234567", "reference": "CCATEST00001",
                  "version": "3.0", "texte-libre": "Démonstration"}
        self.assertEqual(bank.mac(fields, TEST_KEY), "e89f881ac9fcefeecea0b4724b82ed799357bb55")
        self.assertEqual(bank.canonical_fields(fields).decode(), "TPE=1234567*montant=80.00EUR*reference=CCATEST00001*texte-libre=Démonstration*version=3.0")

    def test_form_targets_only_sandbox_and_contains_required_context(self):
        result = bank.payment_form(intent("monetico"), bank_config(),
            {"addressLine1": "1 rue du Test", "city": "Test", "postalCode": "78000", "country": "FR"})
        self.assertEqual(result["action"], "https://p.monetico-services.com/test/paiement.cgi")
        self.assertEqual(result["fields"]["montant"], "80.00EUR")
        self.assertEqual(result["fields"]["date"], "22/09/2026:14:00:00")
        self.assertEqual(result["fields"]["MAC"], bank.mac(result["fields"], TEST_KEY))
        self.assertNotIn(TEST_KEY, repr(result))
        self.assertNotIn("3dsdebrayable", result["fields"])

    def test_form_requires_bound_not_already_authorized_intent(self):
        billing = {"addressLine1": "1 rue du Test", "city": "Test", "postalCode": "78000", "country": "FR"}
        for current in (intent("monetico", bound=False), replace(intent("monetico"), state="authorized")):
            with self.subTest(current=current), self.assertRaises(core.PaymentError):
                bank.payment_form(current, bank_config(), billing)

    def test_missing_or_card_bearing_context_is_refused(self):
        for billing in ({}, {"addressLine1": "test", "city": "test", "postalCode": "78000", "country": "FR", "cvv": "123"}):
            with self.subTest(billing=billing), self.assertRaises(core.PaymentError):
                bank.payment_form(intent("monetico"), bank_config(), billing)

    def test_valid_signed_callback_returns_authorized_not_captured(self):
        event = bank.verify_notification(notification(), intent("monetico"), bank_config())
        self.assertEqual(event.state, "authorized")
        self.assertNotIn("12345678******90", repr(event))
        self.assertNotIn("future-field", repr(event))

    def test_signed_unknown_callback_field_must_not_be_dropped(self):
        raw = notification().replace(b"future-field=signed", b"future-field=changed")
        with self.assertRaisesRegex(core.PaymentError, "notification_mac_invalid"):
            bank.verify_notification(raw, intent("monetico"), bank_config())

    def test_unsigned_or_duplicate_parameters_are_refused(self):
        for raw in (notification() + b"&montant=1.00EUR", notification() + b"&MAC=" + b"0" * 40,
                    notification() + b"&bad=%GG", b"bad", b"x=" + b"a" * bank.MAX_BODY):
            with self.subTest(raw=raw[-30:]), self.assertRaises(core.PaymentError):
                bank.verify_notification(raw, intent("monetico"), bank_config())

    def test_valid_mac_cannot_override_amount_tpe_or_reference(self):
        for change in ({"montant": "1.00EUR"}, {"TPE": "7654321"}, {"reference": "b" * 32}, {"montant": "80.00USD"}):
            with self.subTest(change=change), self.assertRaises(core.PaymentError):
                bank.verify_notification(notification(**change), intent("monetico"), bank_config())

    def test_live_or_installment_success_is_refused_in_sandbox(self):
        for code in ("paiement", "paiement_pf2", "unknown"):
            with self.subTest(code=code), self.assertRaises(core.PaymentError):
                bank.verify_notification(notification(code), intent("monetico"), bank_config())

    def test_decline_and_pending_remain_distinct(self):
        for code, state in (("Annulation", "declined"), ("annulation", "declined"), ("attente_partenaire", "pending")):
            self.assertEqual(bank.verify_notification(notification(code), intent("monetico"), bank_config()).state, state)

    def test_mac_canonicalization_refuses_field_injection(self):
        with self.assertRaises(core.PaymentError):
            bank.mac({"texte-libre": "x*montant=1EUR"}, TEST_KEY)

    def test_acknowledgement_has_exact_lf_format(self):
        self.assertEqual(bank.acknowledgement(True), b"version=2\ncdr=0\n")
        self.assertEqual(bank.acknowledgement(False), b"version=2\ncdr=1\n")
        with self.assertRaises(core.PaymentError):
            bank.acknowledgement("true")


class PaymentJournalTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "payments.sqlite3"
        self.store = core.SandboxJournal(self.path)
        self.quote = core.Quote("private-appointment-id", "technical", 8000, "b" * 64)

    def test_create_is_idempotent_and_rejects_changed_price_or_provider(self):
        first = self.store.create(self.quote, "paypal")
        self.assertEqual(first, self.store.create(self.quote, "paypal"))
        for quote, provider in ((replace(self.quote, amount_cents=7200), "paypal"), (self.quote, "monetico"),
                                (replace(self.quote, terms_hash="c" * 64), "paypal")):
            with self.subTest(provider=provider), self.assertRaises(core.PaymentError):
                self.store.create(quote, provider)

    def test_reference_binding_is_immutable_and_unique(self):
        first = self.store.create(self.quote, "paypal")
        self.store.bind_provider(first.payment_id, ORDER)
        with self.assertRaises(core.PaymentError):
            self.store.bind_provider(first.payment_id, "OTHERORDER88")
        other = self.store.create(replace(self.quote, booking_reference="other-booking"), "paypal")
        with self.assertRaises(core.PaymentError):
            self.store.bind_provider(other.payment_id, ORDER)

    def test_duplicate_notification_has_one_effect_across_restart(self):
        first = self.store.create(self.quote, "monetico")
        first = self.store.bind_provider(first.payment_id, first.payment_id)
        event = core.VerifiedEvent(first.payment_id, "monetico", first.payment_id, "bankevent1", "authorized", 8000)
        self.store._apply_verified(event)
        restarted = core.SandboxJournal(self.path)
        self.assertEqual(restarted._apply_verified(event).state, "authorized")
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM payment_events").fetchone()[0], 1)

    def test_decline_can_be_followed_by_authorization_without_regression(self):
        first = self.store.create(self.quote, "monetico")
        first = self.store.bind_provider(first.payment_id, first.payment_id)
        def event(eid, state):
            return core.VerifiedEvent(first.payment_id, "monetico", first.payment_id, eid, state, 8000)
        self.assertEqual(self.store._apply_verified(event("1", "declined")).state, "declined")
        self.assertEqual(self.store._apply_verified(event("2", "authorized")).state, "authorized")
        self.assertEqual(self.store._apply_verified(event("3", "declined")).state, "authorized")

    def test_forged_binding_and_conflicting_replay_are_refused(self):
        first = self.store.create(self.quote, "monetico")
        first = self.store.bind_provider(first.payment_id, first.payment_id)
        event = core.VerifiedEvent(first.payment_id, "monetico", first.payment_id, "one", "declined", 8000)
        with self.assertRaises(core.PaymentError):
            self.store._apply_verified(replace(event, amount_cents=1))
        self.store._apply_verified(event)
        with self.assertRaises(core.PaymentError):
            self.store._apply_verified(replace(event, state="authorized"))

    def test_concurrent_create_yields_one_intent(self):
        def create(_):
            return self.store.create(self.quote, "paypal").payment_id
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(create, range(20)))
        self.assertEqual(len(set(results)), 1)

    def test_database_does_not_store_booking_reference_and_is_private(self):
        self.store.create(self.quote, "paypal")
        self.assertNotIn(self.quote.booking_reference.encode(), self.path.read_bytes())
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_symlinks_and_public_database_permissions_are_refused(self):
        alias = self.path.parent / "alias.sqlite3"; alias.symlink_to(self.path)
        with self.assertRaises(core.PaymentError):
            core.SandboxJournal(alias)
        self.path.chmod(0o644)
        with self.assertRaises(core.PaymentError):
            core.SandboxJournal(self.path)


if __name__ == "__main__":
    unittest.main()
