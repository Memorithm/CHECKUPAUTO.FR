from __future__ import annotations

import tempfile
import unittest
import uuid
from pathlib import Path

import compliance_store
import data_subject_rights
import rights_completion_plan


class RightsContractCompletionPlanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "compliance.sqlite3"
        self.request = compliance_store.create_rights_request(
            {"type": "access", "subjectRef": "account:42"},
            self.db,
        )
        self.plan = [
            {
                "adapter": "mobile_installation",
                "disposition": "not_applicable",
                "justification": "aucune installation mobile applicable",
            },
            {
                "adapter": "mercure_customer_contact",
                "disposition": "not_applicable",
                "justification": "test isolé de la preuve contractuelle",
            },
            {"adapter": "compliance_contracts", "disposition": "required"},
            {
                "adapter": "contact_requests",
                "disposition": "not_applicable",
                "justification": "aucune demande de contact applicable",
            },
            {
                "adapter": "referral_wallet",
                "disposition": "not_applicable",
                "justification": "aucune cagnotte applicable",
            },
        ]

    def tearDown(self):
        self.tmp.cleanup()

    def _record(self, action: str) -> None:
        data_subject_rights._init_audit(self.db)
        with compliance_store.connect(self.db) as db:
            db.execute(
                """INSERT INTO rights_execution_audit(
                     execution_id,request_id,request_type,adapter,action,evidence_hash,created_at
                   ) VALUES(?,?,?,?,?,?,?)""",
                (
                    uuid.uuid4().hex,
                    self.request["id"],
                    "access",
                    "compliance_contracts",
                    action,
                    "a" * 64,
                    data_subject_rights._now_iso(),
                ),
            )

    def test_contract_plan_requires_export_complete_action(self):
        initial = rights_completion_plan.configure(
            self.request["id"], self.plan, self.db
        )
        self.assertFalse(initial["knownScopeComplete"])

        self._record("export")
        partial = rights_completion_plan.status(self.request["id"], self.db)
        contract = next(
            item for item in partial["items"]
            if item["adapter"] == "compliance_contracts"
        )
        self.assertTrue(contract["executed"])
        self.assertFalse(contract["executionComplete"])
        self.assertEqual(
            contract["executionLimitation"], "partial_contract_store_export"
        )
        self.assertFalse(contract["satisfied"])
        self.assertFalse(partial["knownScopeComplete"])

        self._record("export_complete")
        complete = rights_completion_plan.status(self.request["id"], self.db)
        contract = next(
            item for item in complete["items"]
            if item["adapter"] == "compliance_contracts"
        )
        self.assertTrue(contract["executionComplete"])
        self.assertEqual(contract["executionLimitation"], "")
        self.assertTrue(contract["satisfied"])
        self.assertTrue(complete["knownScopeComplete"])
        self.assertFalse(complete["globalCoverageComplete"])
        self.assertFalse(complete["closureReady"])

    def test_capability_advertises_conditional_contract_completion(self):
        state = rights_completion_plan.capability()
        self.assertEqual(
            state["conditionalCompleteActions"]["compliance_contracts"],
            "export_complete",
        )
        self.assertFalse(state["globalCoverageComplete"])


if __name__ == "__main__":
    unittest.main()
