"""Synthetic, offline tests for server-authoritative pre-Mercure quotes."""
import contextlib
import datetime as dt
import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import compliance_store
import customer_booking_prepayment_quote as module

KEY = "reserve-intent-key-0000000001"
TERMS = "a" * 64


class PrepaymentQuoteTest(unittest.TestCase):
    def setUp(self):
        self.account = {"accountId": "private-account-a",
                        "vehicles": [{"vehicleId": "vehicle-a"}]}
        self.payload = {"service": "technical", "date": "2026-10-16",
                        "time": "09:00", "vehicleId": "vehicle-a", "requestKey": KEY}
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.verify = self.stack.enter_context(patch.object(
            module.booking_bridge, "verify_browser_token", return_value=True))
        self.source = self.stack.enter_context(patch.object(
            module, "_browser_intent", return_value={"service": "technical",
                         "date": "2026-10-16", "time": "09:00"}))
        self.consent = self.stack.enter_context(patch.object(
            module.compliance_store, "checkout_acceptance_for_token",
            return_value={"termsVersion": "2026-10", "termsContentHash": TERMS,
                          "reviewed": True, "immediatePerformance": True,
                          "finalizedContractRef": ""}))
        self.terms = self.stack.enter_context(patch.object(
            module.booking_bridge, "require_published_terms",
            return_value={"version": "2026-10", "contentHash": TERMS}))
        self.need = self.stack.enter_context(patch.object(
            module.booking_bridge, "_checkout_requirements",
            return_value={"requiresImmediatePerformance": True}))
        self.preflight = self.stack.enter_context(patch.object(
            module.customer_booking_api, "preflight",
            return_value={"bookingEnabled": True, "slotAvailableAtCheck": True,
                          "slotHeld": False, "service": "technical",
                          "date": "2026-10-16", "time": "09:00",
                          "vehicleId": "vehicle-a", "priceCents": 8000}))
        self.journal = self.stack.enter_context(patch.object(
            module.customer_booking_journal, "prepare",
            return_value={"state": "prepared"}))

    def quote(self, **kwargs):
        return module.prepare_quote(account=self.account, payload=self.payload,
                                    ccid="signed-intent", cct="synthetic-signature",
                                    **kwargs)

    def test_quote_is_pseudonymous_stable_and_prepared_once(self):
        first, second = self.quote(), self.quote()
        self.assertEqual(first, second)
        self.assertEqual((first.service, first.amount_cents, first.terms_hash),
                         ("technical", 8000, TERMS))
        self.assertTrue(first.booking_reference.startswith("checkupauto-pre:"))
        self.assertNotIn(self.account["accountId"], first.booking_reference)
        self.assertNotIn("vehicle-a", first.booking_reference)
        self.assertNotIn(KEY, first.booking_reference)
        self.assertEqual(self.journal.call_count, 2)
        self.assertEqual(self.journal.call_args.kwargs["request"],
                         {key: self.payload[key] for key in
                          ("service", "date", "time", "vehicleId")})

    def test_signature_and_changed_slot_are_rejected_before_a_payment(self):
        self.verify.return_value = False
        with self.assertRaisesRegex(ValueError, "browser_token_invalid"):
            self.quote()
        self.preflight.assert_not_called()
        self.journal.assert_not_called()
        self.verify.return_value = True
        for field, value in (("date", "2026-10-17"), ("time", "10:00"),
                             ("service", "fitted")):
            with self.subTest(field=field):
                altered = dict(self.payload, **{field: value})
                with self.assertRaisesRegex(ValueError, "browser_intent_mismatch"):
                    module.prepare_quote(account=self.account, payload=altered,
                                         ccid="signed-intent", cct="synthetic-signature")
        self.journal.assert_not_called()

    def test_no_terms_unreviewed_stale_or_already_finalized(self):
        for acceptance in (
            None,
            {"reviewed": False},
            {"reviewed": True, "termsVersion": "2026-10",
             "termsContentHash": "f" * 64, "immediatePerformance": True},
            {"reviewed": True, "termsVersion": "2026-10",
             "termsContentHash": TERMS, "immediatePerformance": True,
             "finalizedContractRef": "Mercure-123"},
            {"reviewed": True, "termsVersion": "2026-10",
             "termsContentHash": TERMS, "immediatePerformance": False},
        ):
            with self.subTest(acceptance=acceptance):
                self.consent.return_value = acceptance
                with self.assertRaises(module.PrepaymentQuoteError):
                    self.quote()
        self.preflight.assert_not_called()
        self.journal.assert_not_called()

    def test_slot_no_longer_available_price_invalid_or_session_off(self):
        for changed in ({"bookingEnabled": False}, {"slotHeld": True},
                        {"slotAvailableAtCheck": False}, {"priceCents": 0},
                        {"priceCents": 8001}, {"vehicleId": "other"}):
            with self.subTest(changed=changed):
                self.preflight.return_value = {
                    "bookingEnabled": True, "slotHeld": False, "slotAvailableAtCheck": True,
                    "service": "technical", "date": "2026-10-16", "time": "09:00",
                    "vehicleId": "vehicle-a", "priceCents": 8000,
                } | changed
                with self.assertRaises(module.PrepaymentQuoteError):
                    self.quote()
        self.journal.assert_not_called()

    def test_cross_account_key_conflict_and_provider_write_claim_blocked(self):
        self.journal.side_effect = module.customer_booking_journal.BookingJournalError(
            "booking_idempotency_conflict"
        )
        with self.assertRaisesRegex(ValueError, "idempotency_conflict"):
            self.quote()
        self.journal.side_effect = None
        self.journal.return_value = {"state": "reconciliation_required"}
        with self.assertRaisesRegex(ValueError, "reconciliation_required"):
            self.quote()

    def test_browser_cannot_supply_banking_or_provider_authority(self):
        for field in ("priceCents", "paymentEvidence", "paid", "lineId", "paymentId"):
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, "prepayment_request_invalid"):
                    module.prepare_quote(
                        account=self.account, payload=self.payload | {field: "forged"},
                        ccid="signed-intent", cct="synthetic-signature",
                    )
        self.preflight.assert_not_called()
        self.journal.assert_not_called()

    def test_reference_binds_customer_and_key(self):
        first = module.reference_for("account-a", KEY)
        self.assertNotEqual(first, module.reference_for("account-b", KEY))
        self.assertNotEqual(first, module.reference_for("account-a", KEY + "-other"))
        self.assertLessEqual(len(first), 120)


class BrowserProofTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        self.db.execute("CREATE TABLE booking_intents("
                        "token TEXT,service TEXT,preferred_date TEXT,"
                        "preferred_time TEXT,created_at TEXT)")
        self.mock = patch.object(module.analytics_store, "connect", return_value=self.db)
        self.mock.start()
        self.addCleanup(self.mock.stop)

    def test_expired_and_unrecognised_tokens_rejected(self):
        now = dt.datetime.now(dt.timezone.utc)
        with self.assertRaisesRegex(ValueError, "not_found"):
            module._browser_intent("missing", now=now)
        self.db.execute("INSERT INTO booking_intents VALUES(?,?,?,?,?)",
                        ("expired", "Contrôle technique", "2026-10-16", "09:00",
                         (now - dt.timedelta(hours=49)).isoformat()))
        with self.assertRaisesRegex(ValueError, "expired"):
            module._browser_intent("expired", now=now)

    def test_recent_source_matches_mercure_label(self):
        now = dt.datetime.now(dt.timezone.utc)
        self.db.execute("INSERT INTO booking_intents VALUES(?,?,?,?,?)",
                        ("recent", "Contrôle technique", "2026-10-16", "09:00",
                         (now - dt.timedelta(minutes=10)).isoformat()))
        source = module._browser_intent("recent", now=now)
        self.assertEqual((source["service"], source["time"]), ("technical", "09:00"))


class ConsentReaderTests(unittest.TestCase):
    def test_read_only_account_receipt_is_not_inferred(self):
        with tempfile.TemporaryDirectory() as root:
            db_path = Path(root) / "consent.sqlite3"
            compliance_store.init_db(db_path)
            self.assertIsNone(compliance_store.checkout_acceptance_for_token(
                "missing", db_path=db_path))
            token = "synthetic-ccid"
            digest = hashlib.sha256(token.encode()).hexdigest()
            with compliance_store.connect(db_path) as db:
                db.execute("""INSERT INTO checkout_acceptance_intents(
                    booking_token_hash,terms_version,terms_content_hash,accepted_at,
                    reviewed,immediate_performance,source,finalized_contract_ref,finalized_at
                ) VALUES(?,?,?,?,?,?,?,'','')""",
                           (digest, "2026-10", TERMS, "2026-10-14T12:00:00Z",
                            1, 1, "checkout_review"))
            receipt = compliance_store.checkout_acceptance_for_token(
                token, db_path=db_path)
            self.assertEqual(receipt["termsContentHash"], TERMS)
            self.assertTrue(receipt["reviewed"])
            self.assertEqual(receipt["finalizedContractRef"], "")
            self.assertIsNone(compliance_store.checkout_acceptance_for_token(
                "another", db_path=db_path))


if __name__ == "__main__":
    unittest.main()
