import json
import tempfile
import unittest
from pathlib import Path

import analytics_store
import compliance_contract_rights
import compliance_store
import data_subject_rights as rights


class ComplianceContractRightsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "compliance.sqlite3"
        self.old_analytics_dir, self.old_analytics_db = analytics_store.DATA_DIR, analytics_store.DB
        analytics_store.DATA_DIR = self.root / "analytics"
        analytics_store.DB = analytics_store.DATA_DIR / "analytics.sqlite3"
        self.contract_ref = "mercure-contract-42"
        self.booking_token = "browser-booking-secret"
        self.attribution_token = "private-attribution-token"
        self.terms = compliance_store.save_document({
            "type": "terms",
            "version": "2026-09-22",
            "title": "Conditions générales de vente",
            "body": "Conditions contractuelles de test. " * 8,
            "action": "publish",
        }, self.db)
        compliance_store.record_checkout_acceptance(
            self.booking_token,
            terms_version=self.terms["version"],
            terms_content_hash=self.terms["contentHash"],
            accepted=True,
            reviewed=True,
            immediate_performance=True,
            db_path=self.db,
        )
        compliance_store.finalize_checkout_acceptance(
            self.booking_token,
            self.contract_ref,
            db_path=self.db,
        )
        compliance_store.record_acceptance("unrelated-contract", db_path=self.db)
        with analytics_store.connect() as db:
            db.executescript("""
                CREATE TABLE booking_conversions(
                  provider TEXT NOT NULL, external_id TEXT NOT NULL, status TEXT NOT NULL,
                  first_seen_at TEXT NOT NULL, updated_at TEXT NOT NULL, confirmed_at TEXT,
                  appointment_at TEXT NOT NULL DEFAULT '', amount_cents INTEGER NOT NULL DEFAULT 0,
                  service TEXT NOT NULL DEFAULT '', attribution_token TEXT NOT NULL DEFAULT '',
                  source TEXT NOT NULL DEFAULT 'Non attribué', campaign TEXT NOT NULL DEFAULT '',
                  device TEXT NOT NULL DEFAULT 'unknown', referral_code TEXT NOT NULL DEFAULT '',
                  PRIMARY KEY(provider,external_id)
                );
            """)
            db.execute(
                "INSERT INTO booking_conversions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("mercure-rdv", self.contract_ref, "confirmed", "2026-09-22T00:00:00+00:00",
                 "2026-09-22T00:01:00+00:00", "2026-09-22T00:01:00+00:00",
                 "2026-10-03T09:30:00+02:00", 8000, "controle technique", self.attribution_token,
                 "Google", "ct-automne", "mobile", "PARRAIN42"),
            )
            db.execute(
                "INSERT INTO booking_conversions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("mercure-rdv", "unrelated-contract", "confirmed", "2026-09-22T00:00:00+00:00",
                 "2026-09-22T00:01:00+00:00", "2026-09-22T00:01:00+00:00",
                 "2026-10-04T10:00:00+02:00", 9000, "vehicule amenage", "other-secret",
                 "Direct", "", "desktop", "OTHER"),
            )

    def tearDown(self):
        analytics_store.DATA_DIR, analytics_store.DB = self.old_analytics_dir, self.old_analytics_db
        self.tmp.cleanup()

    def test_exact_contract_subject_exports_only_bounded_local_evidence(self):
        request = compliance_store.create_rights_request(
            {"type": "access", "subjectRef": self.contract_ref}, self.db,
        )
        result = rights.execute(
            request["id"], self.contract_ref, adapter="compliance_contracts", db_path=self.db,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["requestStatus"], "in_progress")
        self.assertFalse(result["requestComplete"])
        data = result["data"]
        self.assertEqual(data["contractRef"], self.contract_ref)
        self.assertEqual(len(data["consentReceipts"]), 1)
        self.assertEqual(len(data["checkoutAcceptances"]), 1)
        self.assertEqual(len(data["bookingConversions"]), 1)
        self.assertEqual(data["bookingConversions"][0]["amountCents"], 8000)
        self.assertEqual(data["bookingConversions"][0]["referralCode"], "PARRAIN42")
        serialized = json.dumps(result, sort_keys=True)
        self.assertNotIn(self.booking_token, serialized)
        self.assertNotIn(self.attribution_token, serialized)
        self.assertNotIn("unrelated-contract", serialized)
        self.assertNotIn("bookingTokenHash", serialized)
        audit = rights.audit_rows(self.db)
        self.assertEqual(audit[0]["adapter"], "compliance_contracts")
        self.assertNotIn(self.contract_ref, json.dumps(audit[0], sort_keys=True))

    def test_cross_contract_reference_is_refused(self):
        request = compliance_store.create_rights_request(
            {"type": "portability", "subjectRef": self.contract_ref}, self.db,
        )
        with self.assertRaises(PermissionError):
            rights.execute(
                request["id"], "unrelated-contract", adapter="compliance_contracts", db_path=self.db,
            )
        self.assertEqual(rights.audit_rows(self.db), [])

    def test_contract_adapter_remains_partial_only_for_cross_identity_binding(self):
        state = compliance_contract_rights.capability()
        self.assertTrue(state["bound"])
        self.assertTrue(state["partial"])
        self.assertFalse(state["crossIdentityBinding"])
        self.assertEqual(state["remainingStores"], [])
        self.assertIn("booking_conversions", state["coveredStores"])
        global_state = rights.capability(self.db)
        self.assertEqual(global_state["supportedAdapters"]["compliance_contracts"], ["access", "portability"])
        self.assertIn("compliance_contracts", global_state["partialSystemAdapters"])
        self.assertFalse(global_state["bound"])


if __name__ == "__main__":
    unittest.main()
