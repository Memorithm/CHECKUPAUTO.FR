import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import analytics_store as analytics
import booking_bridge as booking
import compliance_store as compliance
import payment_checkout as checkout
import payment_core as core


class TrustedPaymentQuoteTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.env=patch.dict(os.environ, {"CYBERCHECK_DATA_DIR":str(self.root)}, clear=False)
        self.env.start(); self.addCleanup(self.env.stop)
        self.analytics_patch=patch.object(analytics, "DB", self.root/"analytics.sqlite3")
        self.analytics_patch.start(); self.addCleanup(self.analytics_patch.stop)
        self.external_id="RDV-2026-000123"
        self._conversion(self.external_id, "confirmed", "Contrôle technique", 8000)
        self._acceptance(self.external_id, "a"*64)

    def _conversion(self, external_id, status, service, amount):
        with analytics.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS booking_conversions(
              provider TEXT NOT NULL, external_id TEXT NOT NULL, status TEXT NOT NULL,
              first_seen_at TEXT NOT NULL, updated_at TEXT NOT NULL, confirmed_at TEXT,
              appointment_at TEXT NOT NULL DEFAULT '', amount_cents INTEGER NOT NULL DEFAULT 0,
              service TEXT NOT NULL DEFAULT '', attribution_token TEXT NOT NULL DEFAULT '',
              source TEXT NOT NULL DEFAULT 'Non attribué', campaign TEXT NOT NULL DEFAULT '',
              device TEXT NOT NULL DEFAULT 'unknown', PRIMARY KEY(provider,external_id)
            )""")
            db.execute("DELETE FROM booking_conversions WHERE provider=? AND external_id=?",
                       (booking.PROVIDER,external_id))
            db.execute("""INSERT INTO booking_conversions
              (provider,external_id,status,first_seen_at,updated_at,confirmed_at,appointment_at,
               amount_cents,service,attribution_token,source,campaign,device)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (booking.PROVIDER,external_id,status,"2026-09-24T12:00:00+00:00",
               "2026-09-24T12:00:00+00:00","2026-09-24T12:00:00+00:00",
               "2026-10-03T09:00",amount,service,"","Direct","","desktop"))

    def _acceptance(self, external_id, content_hash):
        compliance.init_db()
        with compliance.connect() as db:
            db.execute("DELETE FROM consent_receipts WHERE contract_ref=?", (external_id,))
            db.execute("""INSERT INTO consent_receipts(
              receipt_id,contract_ref,purpose,document_type,document_version,content_hash,
              accepted_at,immediate_performance,source
            ) VALUES(?,?,?,?,?,?,?,?,?)""",
            ("receipt-"+external_id,external_id,"contract_terms","terms","2026-09",
             content_hash,"2026-09-24T11:55:00+00:00",1,"mercure_contract_confirmation"))

    def test_quote_uses_only_authoritative_booking_and_finalized_terms(self):
        quote=checkout.quote_for_confirmed_booking(self.external_id)
        self.assertEqual(quote.service,"technical")
        self.assertEqual(quote.amount_cents,8000)
        self.assertEqual(quote.terms_hash,"a"*64)
        self.assertTrue(quote.booking_reference.startswith("mercure:"))
        self.assertNotIn(self.external_id,quote.booking_reference)

    def test_discounted_authoritative_amount_is_preserved_not_repriced_by_browser(self):
        self._conversion(self.external_id,"confirmed","TOUT VEHICULE HORS CAMPING CAR",7200)
        quote=checkout.quote_for_confirmed_booking(self.external_id)
        self.assertEqual(quote.amount_cents,7200)
        self.assertEqual(quote.service,"technical")

    def test_fitted_service_uses_90_euro_ceiling(self):
        self._conversion(self.external_id,"confirmed","Véhicule aménagé",9000)
        quote=checkout.quote_for_confirmed_booking(self.external_id)
        self.assertEqual((quote.service,quote.amount_cents),("fitted",9000))

    def test_unconfirmed_browser_placeholder_or_unknown_service_is_refused(self):
        for external_id,status,service in (
            ("browser-forged","confirmed","Contrôle technique"),
            (self.external_id,"cancelled","Contrôle technique"),
            (self.external_id,"confirmed","Pollution"),
        ):
            with self.subTest(external_id=external_id,status=status,service=service):
                if not external_id.startswith("browser-"):
                    self._conversion(external_id,status,service,8000)
                with self.assertRaises(core.PaymentError):
                    checkout.quote_for_confirmed_booking(external_id)

    def test_out_of_contract_amount_is_refused(self):
        self._conversion(self.external_id,"confirmed","Contrôle technique",8001)
        with self.assertRaisesRegex(core.PaymentError,"^authoritative_booking_required$"):
            checkout.quote_for_confirmed_booking(self.external_id)

    def test_missing_contract_acceptance_is_refused(self):
        with compliance.connect() as db:
            db.execute("DELETE FROM consent_receipts WHERE contract_ref=?", (self.external_id,))
        with self.assertRaisesRegex(core.PaymentError,"^contract_acceptance_required$"):
            checkout.quote_for_confirmed_booking(self.external_id)

    def test_sandbox_intent_creation_is_idempotent_and_payline_only(self):
        first=checkout.create_sandbox_intent(self.external_id)
        second=checkout.create_sandbox_intent(self.external_id)
        self.assertEqual(first,second)
        self.assertEqual(first["provider"],"payline")
        self.assertEqual(first["amountCents"],8000)
        self.assertEqual(first["state"],"created")
        with self.assertRaisesRegex(core.PaymentError,"^payline_sandbox_required$"):
            checkout.create_sandbox_intent(self.external_id,"paypal")

    def test_capability_keeps_provider_start_and_live_payments_closed(self):
        cap=checkout.capability()
        self.assertTrue(cap["authoritativeBookingBound"])
        self.assertTrue(cap["contractAcceptanceBound"])
        self.assertTrue(cap["serverAuthoritativePrice"])
        self.assertFalse(cap["browserAmountAccepted"])
        self.assertFalse(cap["providerStartBound"])
        self.assertFalse(cap["publicStartRouteBound"])
        self.assertFalse(cap["livePaymentsEnabled"])


if __name__=="__main__":
    unittest.main()
