from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import compliance_store
import contract_subject_rights as contracts
import data_subject_rights


class ContractSubjectRightsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "compliance.sqlite3"
        self.subject = "account:42"

    def tearDown(self):
        self.tmp.cleanup()

    def _request(self, subject: str | None = None) -> dict:
        return compliance_store.create_rights_request(
            {"type": "access", "subjectRef": subject or self.subject},
            self.db,
        )

    @staticmethod
    def _export(complete: bool) -> dict:
        return {
            "provider": "mercure-rdv",
            "contracts": [{"contractRef": "contract-1"}],
            "contractCount": 1,
            "providerAppointmentsComplete": complete,
            "subjectInventory": {
                "state": "attested" if complete else "unconfigured",
                "attested": complete,
                "source": "mercure_complete_appointment_contract_index" if complete else "",
                "evidenceSha256": "a" * 64 if complete else "",
                "reason": "" if complete else "contract_subject_inventory_not_attested",
            },
            "coverageComplete": complete,
            "partial": not complete,
        }

    @patch.object(contracts.compliance_contract_rights, "subject_snapshot")
    @patch.object(contracts.mercure_rights, "contact_snapshot")
    def test_complete_subject_export_records_only_hashed_audit_evidence(
        self, provider_snapshot, subject_snapshot
    ):
        provider_snapshot.return_value = {"coverage": {"appointments": True}}
        subject_snapshot.return_value = self._export(True)
        request = self._request()

        result = contracts.execute(request["id"], self.subject, self.db)

        self.assertTrue(result["ok"])
        self.assertFalse(result["requestComplete"])
        self.assertFalse(result["data"]["partial"])
        audit = data_subject_rights.audit_rows(self.db)
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["adapter"], "compliance_contracts")
        self.assertEqual(audit[0]["action"], "export_complete")
        exposed = repr(audit)
        self.assertNotIn(self.subject, exposed)
        self.assertNotIn("contract-1", exposed)
        self.assertEqual(len(audit[0]["evidenceHash"]), 64)

    @patch.object(contracts.compliance_contract_rights, "subject_snapshot")
    @patch.object(contracts.mercure_rights, "contact_snapshot", return_value={})
    def test_partial_execution_can_retry_until_complete(
        self, provider_snapshot, subject_snapshot
    ):
        subject_snapshot.side_effect = [self._export(False), self._export(True)]
        request = self._request()

        first = contracts.execute(request["id"], self.subject, self.db)
        second = contracts.execute(request["id"], self.subject, self.db)
        self.assertTrue(first["data"]["partial"])
        self.assertFalse(second["data"]["partial"])
        self.assertEqual(
            [row["action"] for row in reversed(data_subject_rights.audit_rows(self.db))],
            ["export", "export_complete"],
        )

        with self.assertRaisesRegex(RuntimeError, "déjà exécuté complètement"):
            contracts.execute(request["id"], self.subject, self.db)
        self.assertEqual(provider_snapshot.call_count, 2)

    @patch.object(contracts.mercure_rights, "contact_snapshot")
    def test_wrong_mercure_subject_is_refused_before_provider_call(self, provider_snapshot):
        request = self._request()
        with self.assertRaises(PermissionError):
            contracts.execute(request["id"], "account:99", self.db)
        provider_snapshot.assert_not_called()
        self.assertEqual(data_subject_rights.audit_rows(self.db), [])

    @patch.object(contracts.data_subject_rights, "execute")
    def test_non_mercure_subject_preserves_legacy_exact_contract_export(self, execute):
        request = self._request("contract-42")
        execute.return_value = {"ok": True, "adapter": "compliance_contracts"}
        result = contracts.execute(request["id"], "contract-42", self.db)
        self.assertTrue(result["ok"])
        execute.assert_called_once_with(
            request["id"],
            "contract-42",
            adapter="compliance_contracts",
            db_path=self.db,
        )

    def test_capability_is_explicit_about_retry_and_legacy_fallback(self):
        state = contracts.capability()
        self.assertEqual(state["adapter"], "compliance_contracts")
        self.assertEqual(state["completeAction"], "export_complete")
        self.assertTrue(state["subjectWideExportReady"])
        self.assertTrue(state["partialRetryAllowedUntilComplete"])
        self.assertTrue(state["requiresVerifiedMercureSubject"])
        self.assertTrue(state["legacyExactContractFallback"])
        self.assertFalse(state["rawSubjectReferencePersisted"])
        self.assertTrue(state["auditStoresEvidenceHashOnly"])


if __name__ == "__main__":
    unittest.main()
