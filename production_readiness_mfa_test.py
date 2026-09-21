import contextlib
import unittest
from unittest import mock

import production_readiness as readiness
from production_readiness_test import CONFIG, SEO_READY, healthy_patches


class ProductionReadinessMFATest(unittest.TestCase):
    def run_with_mfa(self, configured: bool, recovery: int):
        patches = healthy_patches()
        # MFA patches are immediately before the final compliance patch.
        patches[-3] = mock.patch.object(
            readiness.admin_mfa,
            "configured",
            return_value=configured,
        )
        patches[-2] = mock.patch.object(
            readiness.admin_mfa,
            "recovery_remaining",
            return_value=recovery,
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

    def test_missing_admin_mfa_blocks_activation(self):
        result = self.run_with_mfa(False, 0)
        component = next(
            item for item in result["components"]
            if item["id"] == "admin_mfa"
        )
        self.assertEqual(component["state"], "configuration_required")
        self.assertTrue(component["critical"])
        self.assertFalse(result["activationGate"]["allowed"])
        self.assertIn("admin_mfa", result["criticalBlockers"])
        self.assertEqual(
            component["remediation"]["code"],
            "configure_admin_mfa",
        )

    def test_exhausted_recovery_codes_degrade_and_block(self):
        result = self.run_with_mfa(True, 0)
        component = next(
            item for item in result["components"]
            if item["id"] == "admin_mfa"
        )
        self.assertEqual(component["state"], "degraded")
        self.assertTrue(component["metrics"]["configured"])
        self.assertEqual(component["metrics"]["recoveryCodesRemaining"], 0)
        self.assertFalse(result["activationGate"]["allowed"])

    def test_configured_mfa_with_recovery_is_ready(self):
        result = self.run_with_mfa(True, 8)
        component = next(
            item for item in result["components"]
            if item["id"] == "admin_mfa"
        )
        self.assertEqual(component["state"], "ready")
        self.assertEqual(component["metrics"]["recoveryCodesRemaining"], 8)
        self.assertTrue(result["activationGate"]["allowed"])


if __name__ == "__main__":
    unittest.main()
