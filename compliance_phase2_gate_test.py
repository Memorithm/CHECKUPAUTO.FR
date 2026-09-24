import contextlib
import unittest
from unittest import mock

import compliance_admin


class CompliancePhase2GateTest(unittest.TestCase):
    def snapshot(self, *, global_coverage=True, mercure_attested=True,
                 marketing_consent_bound=True, marketing_campaigns_bound=True,
                 local_inventory_complete=True):
        base = {
            "summary": {
                "identityComplete": True,
                "publishedDocuments": 4,
                "requiredDocuments": 4,
                "checkoutAcceptanceBound": True,
                "overdueRightsRequests": 0,
                "overdueIncidentNotifications": 0,
            },
            "rightsRequests": [],
        }
        local_inventory = {
            "scope": "test",
            "inventoryComplete": local_inventory_complete,
            "knownExecutionCoverageComplete": local_inventory_complete,
            "knownStoreCount": 1,
            "unresolvedStoreCount": 0 if local_inventory_complete else 1,
            "unresolvedStores": [] if local_inventory_complete else ["test_store"],
            "stores": [],
            "limitations": [],
        }
        patches = [
            mock.patch.object(compliance_admin.compliance_store, "admin_snapshot", return_value=base),
            mock.patch.object(
                compliance_admin.withdrawal_service,
                "status",
                return_value={"bound": True, "pendingReceipts": 0, "manualMatchRequired": 0},
            ),
            mock.patch.object(
                compliance_admin.compliance_operations,
                "snapshot",
                return_value={"summary": {"activeActivityCount": 1, "activeProcessorCount": 1, "blockers": []}},
            ),
            mock.patch.object(
                compliance_admin.compliance_register_attestation,
                "status",
                return_value={"current": True, "stale": False},
            ),
            mock.patch.object(
                compliance_admin.processing_risk_review,
                "status",
                return_value={"ready": True, "blockers": [], "blockerCount": 0},
            ),
            mock.patch.object(
                compliance_admin.rights_readiness,
                "capability",
                return_value={"bound": True},
            ),
            mock.patch.object(
                compliance_admin,
                "rights_completion_snapshot",
                return_value={
                    "capability": {"globalCoverageComplete": global_coverage},
                    "requestCount": 0,
                    "plans": [],
                },
            ),
            mock.patch.object(
                compliance_admin.retention_enforcement,
                "status",
                return_value={"bound": True, "blockerCount": 0},
            ),
            mock.patch.object(
                compliance_admin.marketing_consent,
                "capability",
                return_value={"bound": marketing_consent_bound},
            ),
            mock.patch.object(compliance_admin.marketing_consent, "recent", return_value=[]),
            mock.patch.object(
                compliance_admin.marketing_campaigns,
                "capability",
                return_value={"bound": marketing_campaigns_bound},
            ),
            mock.patch.object(compliance_admin.marketing_campaigns, "recent_runs", return_value=[]),
            mock.patch.object(
                compliance_admin.mercure_provider_coverage,
                "boundary",
                return_value={
                    "state": "attested" if mercure_attested else "unconfigured",
                    "attested": mercure_attested,
                },
            ),
            mock.patch.object(compliance_admin.mercure_provider_coverage, "capability", return_value={}),
            mock.patch.object(compliance_admin.data_subject_rights, "audit_rows", return_value=[]),
            mock.patch.object(
                compliance_admin.local_privacy_inventory,
                "snapshot",
                return_value=local_inventory,
            ),
        ]
        with contextlib.ExitStack() as stack:
            for patcher in patches:
                stack.enter_context(patcher)
            return compliance_admin.snapshot("ignored.sqlite3")

    def test_all_phase2_evidence_allows_composed_gate(self):
        state = self.snapshot()
        self.assertTrue(state["summary"]["phase2CoverageReady"])
        self.assertEqual(state["summary"]["phase2Blockers"], [])
        self.assertTrue(state["summary"]["readyForPublicContracting"])

    def test_incomplete_global_rights_coverage_blocks_public_contracting(self):
        state = self.snapshot(global_coverage=False)
        self.assertFalse(state["summary"]["phase2CoverageReady"])
        self.assertIn(
            "rights_completion_global_coverage_incomplete",
            state["summary"]["phase2Blockers"],
        )
        self.assertFalse(state["summary"]["readyForPublicContracting"])

    def test_unattested_mercure_boundary_blocks_public_contracting(self):
        state = self.snapshot(mercure_attested=False)
        self.assertFalse(state["summary"]["phase2CoverageReady"])
        self.assertIn(
            "mercure_provider_coverage_unattested",
            state["summary"]["phase2Blockers"],
        )
        self.assertFalse(state["summary"]["readyForPublicContracting"])

    def test_marketing_execution_controls_are_part_of_phase2_gate(self):
        state = self.snapshot(marketing_consent_bound=False, marketing_campaigns_bound=False)
        self.assertFalse(state["summary"]["phase2CoverageReady"])
        self.assertIn("marketing_consent_unbound", state["summary"]["phase2Blockers"])
        self.assertIn("marketing_campaign_execution_unbound", state["summary"]["phase2Blockers"])
        self.assertFalse(state["summary"]["readyForPublicContracting"])

    def test_incomplete_local_privacy_inventory_blocks_public_contracting(self):
        state = self.snapshot(local_inventory_complete=False)
        self.assertFalse(state["summary"]["phase2CoverageReady"])
        self.assertFalse(state["summary"]["localPrivacyInventoryComplete"])
        self.assertEqual(state["summary"]["localPrivacyUnresolvedStoreCount"], 1)
        self.assertIn(
            "local_privacy_store_inventory_incomplete",
            state["summary"]["phase2Blockers"],
        )
        self.assertFalse(state["summary"]["readyForPublicContracting"])


if __name__ == "__main__":
    unittest.main()
