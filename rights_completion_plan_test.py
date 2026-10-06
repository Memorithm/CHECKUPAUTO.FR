from __future__ import annotations

import tempfile
import unittest
import uuid
from pathlib import Path

import compliance_store
import data_subject_rights
import rights_completion_plan


class RightsCompletionPlanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "compliance.sqlite3"

    def tearDown(self):
        self.tmp.cleanup()

    def _request(self, request_type: str = "access") -> dict:
        return compliance_store.create_rights_request(
            {
                "type": request_type,
                "subjectRef": "11111111-1111-1111-1111-111111111111",
                "notes": "",
            },
            self.db_path,
        )

    def _record_execution(
        self,
        request_id: str,
        adapter: str,
        request_type: str = "access",
        *,
        action: str = "test",
        created_at: str | None = None,
        execution_id: str | None = None,
    ) -> None:
        data_subject_rights._init_audit(self.db_path)
        with compliance_store.connect(self.db_path) as db:
            db.execute(
                """INSERT INTO rights_execution_audit(
                     execution_id,request_id,request_type,adapter,action,evidence_hash,created_at
                   ) VALUES(?,?,?,?,?,?,?)""",
                (
                    execution_id or uuid.uuid4().hex,
                    request_id,
                    request_type,
                    adapter,
                    action,
                    "a" * 64,
                    created_at or data_subject_rights._now_iso(),
                ),
            )

    def _access_plan(self, *, wallet_disposition: str = "not_applicable") -> list[dict]:
        rows = [
            {"adapter": "mobile_installation", "disposition": "required"},
            {
                "adapter": "mercure_customer_contact",
                "disposition": "not_applicable",
                "justification": "aucun compte Mercure n'est lié à cette installation",
            },
            {
                "adapter": "compliance_contracts",
                "disposition": "not_applicable",
                "justification": "aucun contrat CheckupAuto n'est lié à cette installation",
            },
            {
                "adapter": "contact_requests",
                "disposition": "not_applicable",
                "justification": "aucune demande de contact n'est liée à cette installation",
            },
            {
                "adapter": "customer_account",
                "disposition": "not_applicable",
                "justification": "aucun compte client web n'est lié à cette installation",
            },
        ]
        if wallet_disposition == "required":
            rows.append({"adapter": "referral_wallet", "disposition": "required"})
        else:
            rows.append(
                {
                    "adapter": "referral_wallet",
                    "disposition": "not_applicable",
                    "justification": "aucune cagnotte n'est rattachée à cette installation",
                }
            )
        return rows

    def _mercure_required_access_plan(self) -> list[dict]:
        return [
            {
                "adapter": "contact_requests",
                "disposition": "not_applicable",
                "justification": "aucune demande de contact n'est liée à cette identité Mercure",
            },
            {
                "adapter": "customer_account",
                "disposition": "not_applicable",
                "justification": "aucun compte client web n'est lié à cette identité Mercure",
            },
            {
                "adapter": "mobile_installation",
                "disposition": "not_applicable",
                "justification": "aucune installation mobile ne correspond à la demande",
            },
            {"adapter": "mercure_customer_contact", "disposition": "required"},
            {
                "adapter": "compliance_contracts",
                "disposition": "not_applicable",
                "justification": "aucun contrat local ne correspond à la demande",
            },
            {
                "adapter": "referral_wallet",
                "disposition": "not_applicable",
                "justification": "aucune cagnotte ne correspond à la demande",
            },
        ]

    def test_plan_requires_exact_classification_of_every_known_adapter(self):
        request = self._request()
        with self.assertRaises(ValueError):
            rights_completion_plan.configure(
                request["id"],
                [{"adapter": "mobile_installation", "disposition": "required"}],
                self.db_path,
            )

        state = rights_completion_plan.status(request["id"], self.db_path)
        self.assertFalse(state["planComplete"])
        self.assertFalse(state["knownScopeComplete"])
        self.assertFalse(state["closureReady"])
        self.assertEqual(
            state["knownAdapters"],
            [
                "compliance_contracts",
                "contact_requests",
                "customer_account",
                "mercure_customer_contact",
                "mobile_installation",
                "referral_wallet",
            ],
        )

    def test_not_applicable_requires_hashed_justification_and_never_persists_raw_text(self):
        request = self._request()
        marker = "RAW-JUSTIFICATION-MUST-NOT-PERSIST"
        plan = self._access_plan()
        plan[1]["justification"] = marker
        state = rights_completion_plan.configure(request["id"], plan, self.db_path)

        mercure = next(item for item in state["items"] if item["adapter"] == "mercure_customer_contact")
        self.assertEqual(len(mercure["justificationHash"]), 64)
        self.assertNotEqual(mercure["justificationHash"], marker)
        self.assertFalse(state["rawJustificationPersisted"])

        raw = self.db_path.read_bytes()
        self.assertNotIn(marker.encode("utf-8"), raw)

        invalid = self._access_plan()
        invalid[1]["justification"] = ""
        with self.assertRaises(ValueError):
            rights_completion_plan.configure(request["id"], invalid, self.db_path)

    def test_executed_adapter_cannot_be_reclassified_not_applicable(self):
        request = self._request()
        self._record_execution(request["id"], "referral_wallet")
        with self.assertRaises(ValueError):
            rights_completion_plan.configure(
                request["id"],
                self._access_plan(wallet_disposition="not_applicable"),
                self.db_path,
            )

    def test_known_scope_completion_is_derived_from_complete_mobile_execution(self):
        request = self._request()
        state = rights_completion_plan.configure(request["id"], self._access_plan(), self.db_path)
        self.assertFalse(state["knownScopeComplete"])

        self._record_execution(request["id"], "mobile_installation")
        state = rights_completion_plan.status(request["id"], self.db_path)
        self.assertTrue(state["planComplete"])
        self.assertTrue(state["knownScopeComplete"])
        self.assertFalse(state["globalCoverageComplete"])
        self.assertFalse(state["closureReady"])
        required = next(item for item in state["items"] if item["adapter"] == "mobile_installation")
        self.assertTrue(required["executed"])
        self.assertTrue(required["executionComplete"])
        self.assertEqual(required["executionLimitation"], "")
        self.assertTrue(required["satisfied"])

    def test_partial_mercure_execution_never_satisfies_required_plan_item(self):
        request = self._request()
        rights_completion_plan.configure(
            request["id"],
            self._mercure_required_access_plan(),
            self.db_path,
        )
        self._record_execution(request["id"], "mercure_customer_contact")

        state = rights_completion_plan.status(request["id"], self.db_path)
        mercure = next(item for item in state["items"] if item["adapter"] == "mercure_customer_contact")
        self.assertTrue(mercure["executed"])
        self.assertFalse(mercure["executionComplete"])
        self.assertEqual(mercure["executionLimitation"], "bounded_provider_export")
        self.assertFalse(mercure["satisfied"])
        self.assertFalse(state["knownScopeComplete"])
        self.assertFalse(state["closureReady"])

    def test_complete_mercure_export_satisfies_known_item_but_not_global_closure(self):
        request = self._request()
        rights_completion_plan.configure(
            request["id"],
            self._mercure_required_access_plan(),
            self.db_path,
        )
        self._record_execution(
            request["id"],
            "mercure_customer_contact",
            action="export_complete",
        )

        state = rights_completion_plan.status(request["id"], self.db_path)
        mercure = next(item for item in state["items"] if item["adapter"] == "mercure_customer_contact")
        self.assertTrue(mercure["executed"])
        self.assertTrue(mercure["executionComplete"])
        self.assertEqual(mercure["executionLimitation"], "")
        self.assertTrue(mercure["satisfied"])
        self.assertTrue(state["knownScopeComplete"])
        self.assertFalse(state["globalCoverageComplete"])
        self.assertFalse(state["closureReady"])
        with self.assertRaisesRegex(RuntimeError, "couverture globale"):
            rights_completion_plan.close(request["id"], self.db_path)

    def test_complete_mercure_action_wins_without_timestamp_or_uuid_ordering(self):
        request = self._request()
        rights_completion_plan.configure(
            request["id"],
            self._mercure_required_access_plan(),
            self.db_path,
        )
        same_second = "2026-09-23T05:30:00+00:00"
        # Deliberately sort the completion UUID before the partial UUID. A
        # last-row-wins implementation would incorrectly end in partial state.
        self._record_execution(
            request["id"],
            "mercure_customer_contact",
            action="export_complete",
            created_at=same_second,
            execution_id="0" * 32,
        )
        self._record_execution(
            request["id"],
            "mercure_customer_contact",
            action="export",
            created_at=same_second,
            execution_id="f" * 32,
        )

        state = rights_completion_plan.status(request["id"], self.db_path)
        mercure = next(item for item in state["items"] if item["adapter"] == "mercure_customer_contact")
        self.assertTrue(mercure["executionComplete"])
        self.assertTrue(mercure["satisfied"])
        self.assertEqual(mercure["executionLimitation"], "")
        self.assertTrue(state["knownScopeComplete"])
        self.assertFalse(state["closureReady"])

    def test_partial_rectification_execution_is_not_completion_proof(self):
        request = self._request("rectification")
        rights_completion_plan.configure(
            request["id"],
            [{"adapter": "mobile_deadline_rectification", "disposition": "required"}],
            self.db_path,
        )
        self._record_execution(
            request["id"],
            "mobile_deadline_rectification",
            "rectification",
        )

        state = rights_completion_plan.status(request["id"], self.db_path)
        item = state["items"][0]
        self.assertTrue(item["executed"])
        self.assertFalse(item["executionComplete"])
        self.assertEqual(item["executionLimitation"], "local_deadline_field_only")
        self.assertFalse(item["satisfied"])
        self.assertFalse(state["knownScopeComplete"])
        with self.assertRaisesRegex(RuntimeError, "plan d'exécution incomplet"):
            rights_completion_plan.close(request["id"], self.db_path)

    def test_close_fails_closed_while_global_store_coverage_is_incomplete(self):
        request = self._request("access")
        rights_completion_plan.configure(request["id"], self._access_plan(), self.db_path)
        self._record_execution(request["id"], "mobile_installation", "access")

        state = rights_completion_plan.status(request["id"], self.db_path)
        self.assertTrue(state["knownScopeComplete"])
        with self.assertRaisesRegex(RuntimeError, "couverture globale"):
            rights_completion_plan.close(request["id"], self.db_path)

        current = next(
            row for row in compliance_store.rights_requests(self.db_path)
            if row["id"] == request["id"]
        )
        self.assertEqual(current["status"], "open")
        self.assertEqual(current["closedAt"], "")

    def test_plan_is_rejected_after_request_is_closed_or_rejected(self):
        request = self._request("rectification")
        compliance_store.set_rights_request_status(request["id"], "rejected", self.db_path)
        with self.assertRaises(RuntimeError):
            rights_completion_plan.configure(
                request["id"],
                [{"adapter": "mobile_deadline_rectification", "disposition": "required"}],
                self.db_path,
            )

    def test_capability_does_not_overstate_cross_store_completion(self):
        capability = rights_completion_plan.capability()
        self.assertTrue(capability["planReady"])
        self.assertEqual(capability["coverageScope"], "implemented_adapters")
        self.assertFalse(capability["globalCoverageComplete"])
        self.assertTrue(capability["closureFailClosedOnGlobalCoverage"])
        self.assertTrue(capability["partialExecutionDoesNotSatisfyRequiredPlan"])
        self.assertEqual(
            capability["partialExecutionAdapters"]["mercure_customer_contact"],
            "bounded_provider_export",
        )
        self.assertEqual(
            capability["conditionalCompleteActions"]["mercure_customer_contact"],
            "export_complete",
        )
        self.assertTrue(capability["notApplicableRequiresHashedJustification"])
        self.assertFalse(capability["rawJustificationPersisted"])


if __name__ == "__main__":
    unittest.main()
