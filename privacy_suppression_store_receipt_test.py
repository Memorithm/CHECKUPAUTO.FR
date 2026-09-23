import os
import tempfile
import unittest
from pathlib import Path

import compliance_store
import data_subject_rights as rights
import marketing_consent
import privacy_suppression


class PrivacySuppressionStoreReceiptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old_private = os.environ.get("CYBERCHECK_PRIVATE_DIR")
        os.environ["CYBERCHECK_PRIVATE_DIR"] = self.tmp.name
        self.addCleanup(self._restore)
        self.db = Path(self.tmp.name) / "compliance.sqlite3"
        marketing_consent.init_db(self.db)

    def _restore(self):
        if self.old_private is None:
            os.environ.pop("CYBERCHECK_PRIVATE_DIR", None)
        else:
            os.environ["CYBERCHECK_PRIVATE_DIR"] = self.old_private

    def _consent(self, email="alice@example.test"):
        return marketing_consent.record_consent(
            {
                "channel": "email",
                "subjectRef": email,
                "controllerName": "Checkup Auto",
                "thirdPartyName": "",
                "goodsServicesScope": "Offres et services Checkup Auto liés au contrôle technique automobile",
                "statementVersion": "1.0",
                "statementText": (
                    "J’accepte de recevoir des offres commerciales Checkup Auto par e-mail. "
                    "Mon consentement peut être retiré à tout moment."
                ),
                "source": "rights-store-receipt-test",
                "evidenceRef": "evidence-store-receipt",
                "withdrawalMethod": "Demande auprès de Checkup Auto ou lien de désinscription.",
                "positiveAction": True,
            },
            self.db,
        )

    def _request(self, request_type, subject_ref):
        return compliance_store.create_rights_request(
            {"type": request_type, "subjectRef": subject_ref},
            self.db,
        )

    def test_consent_withdrawal_mutates_marketing_store_and_persists_minimized_receipt(self):
        email = "alice@example.test"
        self._consent(email)
        request = self._request("consent_withdrawal", email)

        result = rights.execute(
            request["id"],
            email,
            adapter="privacy_suppression",
            purpose="direct_marketing_email",
            db_path=self.db,
        )

        self.assertTrue(result["identityResolutionComplete"])
        proof = marketing_consent.proof("email", email, db_path=self.db)
        self.assertEqual(proof["records"][0]["state"], "withdrawn")
        self.assertEqual(
            proof["records"][0]["withdrawalSource"],
            "data-subject-rights",
        )
        receipts = privacy_suppression.store_receipts(request["id"], self.db)
        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts[0]["store"], "marketing_consent")
        self.assertEqual(receipts[0]["scope"], "email")
        self.assertEqual(receipts[0]["operation"], "withdraw")
        self.assertEqual(receipts[0]["affectedRows"], 1)
        self.assertEqual(receipts[0]["remainingActiveRows"], 0)
        self.assertEqual(len(receipts[0]["evidenceHash"]), 64)
        self.assertNotIn(email, repr(receipts))
        self.assertNotIn(email.encode(), self.db.read_bytes())
        self.assertEqual(rights.audit_rows(self.db)[0]["action"], "suppress_complete")

    def test_objection_blocks_marketing_without_relabelling_consent_as_withdrawn(self):
        email = "alice@example.test"
        self._consent(email)
        request = self._request("objection", email)

        rights.execute(
            request["id"],
            email,
            adapter="privacy_suppression",
            purpose="direct_marketing_email",
            db_path=self.db,
        )

        proof = marketing_consent.proof("email", email, db_path=self.db)
        self.assertEqual(proof["records"][0]["state"], "active")
        denied = marketing_consent.authorize("email", email, db_path=self.db)
        self.assertFalse(denied["authorized"])
        self.assertEqual(denied["reason"], "privacy_suppressed")
        self.assertEqual(privacy_suppression.store_receipts(request["id"], self.db), [])

    def test_receipt_is_idempotent_when_same_suppression_is_reverified(self):
        email = "alice@example.test"
        self._consent(email)
        request = self._request("consent_withdrawal", email)

        first = privacy_suppression.suppress(
            "email",
            email,
            ["direct_marketing_email"],
            request_id=request["id"],
            db_path=self.db,
        )
        second = privacy_suppression.suppress(
            "email",
            email,
            ["direct_marketing_email"],
            request_id=request["id"],
            db_path=self.db,
        )

        self.assertEqual(first["storeReceiptCount"], 1)
        self.assertEqual(second["storeReceiptCount"], 1)
        receipts = privacy_suppression.store_receipts(request["id"], self.db)
        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts[0]["affectedRows"], 1)
        self.assertEqual(receipts[0]["remainingActiveRows"], 0)
        self.assertEqual(first["storeReceipts"][0]["evidenceHash"], receipts[0]["evidenceHash"])
        self.assertEqual(second["storeReceipts"][0]["evidenceHash"], receipts[0]["evidenceHash"])


if __name__ == "__main__":
    unittest.main()
