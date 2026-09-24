import tempfile
import unittest
from pathlib import Path

import compliance_store
import data_subject_rights
import rights_execution_dispatch
import withdrawal_rights
import withdrawal_service


class WithdrawalRightsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "compliance.sqlite3"

    def tearDown(self):
        self.tmp.cleanup()

    def _rights_request(self, request_type="access", subject="alice@example.test"):
        return compliance_store.create_rights_request(
            {"type": request_type, "subjectRef": subject, "notes": "test withdrawal export"},
            self.db_path,
        )

    def _withdrawal(self, email="alice@example.test"):
        return withdrawal_service.submit(
            {
                "firstName": "Alice",
                "lastName": "Martin",
                "contractRef": "RDV-TEST-001",
                "receiptEmail": email,
                "confirm": True,
            },
            self.db_path,
            dispatch=False,
        )

    def test_access_exports_withdrawal_by_persisted_email_hash(self):
        request = self._rights_request()
        submitted = self._withdrawal()
        with compliance_store.connect(self.db_path) as db:
            db.execute(
                "UPDATE withdrawal_requests SET receipt_email='',receipt_status='sent' WHERE request_id=?",
                (submitted["id"],),
            )

        result = rights_execution_dispatch.execute(
            {
                "id": request["id"],
                "subjectRef": "alice@example.test",
                "adapter": withdrawal_rights.ADAPTER,
            },
            self.db_path,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["requestType"], "access")
        self.assertEqual(result["data"]["recordCount"], 1)
        self.assertEqual(result["data"]["lookup"], "receipt_email_hash")
        self.assertTrue(result["data"]["localLookupCompleteForEmail"])
        self.assertFalse(result["data"]["subjectCoverageComplete"])
        self.assertTrue(result["data"]["partial"])
        row = result["data"]["records"][0]
        self.assertEqual(row["requestId"], submitted["id"])
        self.assertEqual(row["firstName"], "Alice")
        self.assertEqual(row["lastName"], "Martin")
        self.assertEqual(row["contractRef"], "RDV-TEST-001")
        self.assertEqual(row["receiptEmail"], "")

        audit = data_subject_rights.audit_rows(self.db_path)
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["adapter"], withdrawal_rights.ADAPTER)
        self.assertEqual(audit[0]["action"], "export")
        self.assertNotIn("alice@example.test", repr(audit))
        self.assertNotIn("RDV-TEST-001", repr(audit))

    def test_portability_is_supported_but_erasure_is_not_invented(self):
        portability = self._rights_request("portability")
        result = rights_execution_dispatch.execute(
            {
                "id": portability["id"],
                "subjectRef": "alice@example.test",
                "adapter": withdrawal_rights.ADAPTER,
            },
            self.db_path,
        )
        self.assertEqual(result["requestType"], "portability")
        self.assertEqual(result["data"]["records"], [])

        erasure = self._rights_request("erasure")
        with self.assertRaises(NotImplementedError):
            rights_execution_dispatch.execute(
                {
                    "id": erasure["id"],
                    "subjectRef": "alice@example.test",
                    "adapter": withdrawal_rights.ADAPTER,
                },
                self.db_path,
            )

    def test_subject_reference_must_match_verified_rights_request(self):
        request = self._rights_request(subject="alice@example.test")
        self._withdrawal(email="bob@example.test")

        with self.assertRaises(PermissionError):
            rights_execution_dispatch.execute(
                {
                    "id": request["id"],
                    "subjectRef": "bob@example.test",
                    "adapter": withdrawal_rights.ADAPTER,
                },
                self.db_path,
            )

    def test_capability_is_explicitly_partial_and_retention_governed(self):
        cap = rights_execution_dispatch.capability(self.db_path)
        self.assertEqual(
            cap["supportedAdapters"][withdrawal_rights.ADAPTER],
            ["access", "portability"],
        )
        withdrawal = cap["withdrawalEvidence"]
        self.assertFalse(withdrawal["subjectCoverageComplete"])
        self.assertFalse(withdrawal["erasureImplemented"])
        self.assertEqual(withdrawal["retentionRule"], "withdrawal_evidence")
        self.assertFalse(cap["globalCoverageComplete"])


if __name__ == "__main__":
    unittest.main()
