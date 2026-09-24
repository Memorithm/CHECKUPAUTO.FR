import datetime
import tempfile
import unittest
from pathlib import Path

import compliance_store
import data_subject_rights
import retention_enforcement
import rights_execution_dispatch
import withdrawal_rights
import withdrawal_service


class WithdrawalRightsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "compliance.sqlite3"

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def _iso(days_ago):
        return (
            datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(days=days_ago)
        ).isoformat(timespec="seconds")

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

    def _retention_policy(self, days=30):
        return retention_enforcement.save_policy(
            {
                "ruleId": "withdrawal_evidence",
                "activeDays": days,
                "justification": "Conservation probatoire validée pour les tests de rétractation.",
                "legalReviewConfirmed": True,
                "enabled": True,
            },
            self.db_path,
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

    def test_portability_is_supported(self):
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

    def test_erasure_deletes_only_expired_rows_under_validated_policy(self):
        erasure = self._rights_request("erasure")
        old = self._withdrawal()
        recent = self._withdrawal()
        with compliance_store.connect(self.db_path) as db:
            db.execute(
                "UPDATE withdrawal_requests SET submitted_at=? WHERE request_id=?",
                (self._iso(45), old["id"]),
            )
            db.execute(
                "UPDATE withdrawal_requests SET submitted_at=? WHERE request_id=?",
                (self._iso(2), recent["id"]),
            )
        self._retention_policy(30)

        result = rights_execution_dispatch.execute(
            {
                "id": erasure["id"],
                "subjectRef": "alice@example.test",
                "adapter": withdrawal_rights.ADAPTER,
            },
            self.db_path,
        )

        evidence = result["data"]
        self.assertEqual(result["requestType"], "erasure")
        self.assertTrue(evidence["retentionPolicyReady"])
        self.assertTrue(evidence["legalReviewConfirmed"])
        self.assertEqual(evidence["activeDays"], 30)
        self.assertEqual(evidence["matchedCount"], 2)
        self.assertEqual(evidence["erasedCount"], 1)
        self.assertEqual(evidence["retainedCount"], 1)
        self.assertEqual(evidence["retainedMalformedTimestampCount"], 0)
        self.assertFalse(evidence["subjectCoverageComplete"])
        with compliance_store.connect(self.db_path) as db:
            rows = db.execute(
                "SELECT request_id FROM withdrawal_requests ORDER BY request_id"
            ).fetchall()
        self.assertEqual([row["request_id"] for row in rows], [recent["id"]])

        audit = data_subject_rights.audit_rows(self.db_path)
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["action"], "erase_retention_applied")
        self.assertNotIn("alice@example.test", repr(audit))
        self.assertNotIn("RDV-TEST-001", repr(audit))

    def test_erasure_fails_closed_without_validated_retention_policy(self):
        erasure = self._rights_request("erasure")
        submitted = self._withdrawal()
        with compliance_store.connect(self.db_path) as db:
            db.execute(
                "UPDATE withdrawal_requests SET submitted_at=? WHERE request_id=?",
                (self._iso(45), submitted["id"]),
            )

        with self.assertRaises(RuntimeError):
            rights_execution_dispatch.execute(
                {
                    "id": erasure["id"],
                    "subjectRef": "alice@example.test",
                    "adapter": withdrawal_rights.ADAPTER,
                },
                self.db_path,
            )

        with compliance_store.connect(self.db_path) as db:
            remaining = db.execute(
                "SELECT COUNT(*) n FROM withdrawal_requests WHERE request_id=?",
                (submitted["id"],),
            ).fetchone()["n"]
        self.assertEqual(remaining, 1)
        self.assertEqual(data_subject_rights.audit_rows(self.db_path), [])

    def test_erasure_retains_malformed_timestamp_instead_of_guessing_expiry(self):
        erasure = self._rights_request("erasure")
        submitted = self._withdrawal()
        with compliance_store.connect(self.db_path) as db:
            db.execute(
                "UPDATE withdrawal_requests SET submitted_at='not-a-timestamp' WHERE request_id=?",
                (submitted["id"],),
            )
        self._retention_policy(30)

        result = rights_execution_dispatch.execute(
            {
                "id": erasure["id"],
                "subjectRef": "alice@example.test",
                "adapter": withdrawal_rights.ADAPTER,
            },
            self.db_path,
        )

        self.assertEqual(result["data"]["erasedCount"], 0)
        self.assertEqual(result["data"]["retainedCount"], 1)
        self.assertEqual(result["data"]["retainedMalformedTimestampCount"], 1)

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
            ["access", "portability", "erasure"],
        )
        withdrawal = cap["withdrawalEvidence"]
        self.assertFalse(withdrawal["subjectCoverageComplete"])
        self.assertTrue(withdrawal["erasureImplemented"])
        self.assertTrue(withdrawal["erasureRequiresReadyValidatedRetentionPolicy"])
        self.assertEqual(withdrawal["retentionRule"], "withdrawal_evidence")
        self.assertFalse(cap["globalCoverageComplete"])


if __name__ == "__main__":
    unittest.main()
