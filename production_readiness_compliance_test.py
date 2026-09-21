import contextlib
import json
import unittest
from unittest import mock

import production_readiness as readiness
from production_readiness_test import CONFIG, SEO_READY, healthy_patches


class ProductionReadinessComplianceTest(unittest.TestCase):
    def run_with_compliance(self, summary):
        patches = healthy_patches()
        patches[-1] = mock.patch.object(
            readiness.compliance_admin,
            "snapshot",
            return_value={"summary": summary},
        )
        with contextlib.ExitStack() as stack:
            for patcher in patches:
                stack.enter_context(patcher)
            stack.enter_context(mock.patch.object(
                readiness.referral_integrity_audit,
                "status",
                return_value={"ok": True, "state": "ready", "issues": 0, "metrics": {}},
            ))
            return readiness.status(CONFIG, SEO_READY)

    def test_operational_compliance_blocker_closes_activation_gate(self):
        result = self.run_with_compliance({
            "readyForPublicContracting": False,
            "operationalRegistersReady": False,
            "identityComplete": True,
            "publishedDocuments": 4,
            "requiredDocuments": 4,
            "checkoutAcceptanceBound": False,
            "withdrawalFunctionBound": False,
            "overdueRightsRequests": 0,
            "overdueIncidentNotifications": 0,
            "operationalBlockers": [{"type": "processing_register_missing"}],
        })
        component = next(item for item in result["components"] if item["id"] == "compliance")
        self.assertEqual(component["state"], "degraded")
        self.assertTrue(component["critical"])
        self.assertEqual(component["metrics"]["operationalBlockerCount"], 1)
        self.assertFalse(result["launchReady"])
        self.assertIn("compliance", result["criticalBlockers"])
        self.assertFalse(result["activationGate"]["allowed"])

    def test_missing_contract_controls_are_configuration_required_and_critical(self):
        result = self.run_with_compliance({
            "readyForPublicContracting": False,
            "operationalRegistersReady": True,
            "identityComplete": True,
            "publishedDocuments": 4,
            "requiredDocuments": 4,
            "checkoutAcceptanceBound": False,
            "withdrawalFunctionBound": False,
            "overdueRightsRequests": 0,
            "overdueIncidentNotifications": 0,
            "operationalBlockers": [],
        })
        component = next(item for item in result["components"] if item["id"] == "compliance")
        self.assertEqual(component["state"], "configuration_required")
        self.assertFalse(component["metrics"]["checkoutAcceptanceBound"])
        self.assertFalse(component["metrics"]["withdrawalFunctionBound"])
        self.assertFalse(result["activationGate"]["allowed"])
        self.assertEqual(component["remediation"]["code"], "complete_compliance_controls")

    def test_compliance_snapshot_failure_fails_closed_without_leaking_error_detail(self):
        patches = healthy_patches()
        patches[-1] = mock.patch.object(
            readiness.compliance_admin,
            "snapshot",
            side_effect=RuntimeError("private-compliance-detail"),
        )
        with contextlib.ExitStack() as stack:
            for patcher in patches:
                stack.enter_context(patcher)
            stack.enter_context(mock.patch.object(
                readiness.referral_integrity_audit,
                "status",
                return_value={"ok": True, "state": "ready", "issues": 0, "metrics": {}},
            ))
            result = readiness.status(CONFIG, SEO_READY)
        component = next(item for item in result["components"] if item["id"] == "compliance")
        self.assertEqual(component["state"], "degraded")
        self.assertTrue(component["critical"])
        self.assertFalse(result["activationGate"]["allowed"])
        self.assertIn("compliance", result["criticalBlockers"])
        self.assertNotIn("private-compliance-detail", json.dumps(result))
        self.assertIn("RuntimeError", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
