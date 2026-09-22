import json
import tempfile
import unittest
from pathlib import Path

import compliance_contract_rights
import compliance_store
import data_subject_rights as rights


class ComplianceContractRightsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "compliance.sqlite3"
        self.contract_ref = "mercure-contract-42"
        self.booking_token = "browser-booking-secret"
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
        compliance_store.record_acceptance(
            "unrelated-contract",
            db_path=self.db,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_exact_contract_subject_exports_only_bounded_local_evidence(self):
        request = compliance_store.create_rights_request(
            {"type": "access", "subjectRef": self.contract_ref},
            self.db,
        )
        result = rights.execute(
            request["id"],
            self.contract_ref,
            adapter="compliance_contracts",
            db_path=self.db,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["requestStatus"], "in_progress")
        self.assertFalse(result["requestComplete"])
        data = result["data"]
        self.assertEqual(data["contractRef"], self.contract_ref)
        self.assertEqual(len(data["consentReceipts"]), 1)
        self.assertEqual(len(data["checkoutAcceptances"]), 1)
        serialized = json.dumps(result, sort_keys=True)
        self.assertNotIn(self.booking_token, serialized)
        self.assertNotIn("unrelated-contract", serialized)
        self.assertNotIn("bookingTokenHash", serialized)
        audit = rights.audit_rows(self.db)
        self.assertEqual(audit[0]["adapter"], "compliance_contracts")
        self.assertNotIn(self.contract_ref, json.dumps(audit[0], sort_keys=True))

    def test_cross_contract_reference_is_refused(self):
        request = compliance_store.create_rights_request(
            {"type": "portability", "subjectRef": self.contract_ref},
            self.db,
        )
        with self.assertRaises(PermissionError):
            rights.execute(
                request["id"],
                "unrelated-contract",
                adapter="compliance_contracts",
                db_path=self.db,
            )
        self.assertEqual(rights.audit_rows(self.db), [])

    def test_contract_adapter_remains_explicitly_partial(self):
        state = compliance_contract_rights.capability()
        self.assertTrue(state["bound"])
        self.assertTrue(state["partial"])
        self.assertFalse(state["crossIdentityBinding"])
        self.assertIn("booking_conversions", state["remainingStores"])
        global_state = rights.capability(self.db)
        self.assertEqual(
            global_state["supportedAdapters"]["compliance_contracts"],
            ["access", "portability"],
        )
        self.assertIn("compliance_contracts", global_state["partialSystemAdapters"])
        self.assertFalse(global_state["bound"])


if __name__ == "__main__":
    unittest.main()
