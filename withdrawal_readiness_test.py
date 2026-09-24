from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import retention_enforcement
import rights_readiness
import withdrawal_readiness


class WithdrawalReadinessTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "compliance.sqlite3"

    def tearDown(self):
        self.tmp.cleanup()

    def test_erasure_is_not_executable_without_validated_policy(self):
        state = withdrawal_readiness.capability(self.db_path)

        self.assertTrue(state["erasureImplemented"])
        self.assertFalse(state["erasureExecutable"])
        policy = state["retentionPolicy"]
        self.assertEqual(policy["id"], "withdrawal_evidence")
        self.assertFalse(policy["configured"])
        self.assertFalse(policy["ready"])
        self.assertEqual(policy["blocker"], "policy_configuration_required")

    def test_erasure_becomes_executable_only_with_ready_legal_policy(self):
        retention_enforcement.save_policy(
            {
                "ruleId": "withdrawal_evidence",
                "activeDays": 45,
                "justification": "Conservation probatoire validée pour la rétractation.",
                "legalReviewConfirmed": True,
                "enabled": True,
            },
            self.db_path,
        )

        state = withdrawal_readiness.capability(self.db_path)

        self.assertTrue(state["erasureExecutable"])
        policy = state["retentionPolicy"]
        self.assertTrue(policy["configured"])
        self.assertTrue(policy["enabled"])
        self.assertTrue(policy["implemented"])
        self.assertTrue(policy["legalReviewConfirmed"])
        self.assertTrue(policy["ready"])
        self.assertEqual(policy["activeDays"], 45)
        self.assertEqual(policy["blocker"], "")

    def test_policy_read_failure_is_fail_closed_and_does_not_leak_error(self):
        with mock.patch.object(
            withdrawal_readiness.retention_enforcement,
            "policy",
            side_effect=RuntimeError("/private/runtime/secret.sqlite3"),
        ):
            state = withdrawal_readiness.capability(self.db_path)

        self.assertFalse(state["erasureExecutable"])
        self.assertEqual(
            state["retentionPolicy"]["blocker"],
            "retention_policy_unavailable",
        )
        self.assertNotIn("secret.sqlite3", repr(state))

    def test_composed_rights_readiness_surfaces_adapter_without_overstating_global_bound(self):
        withdrawal = {
            "adapter": "withdrawal_evidence",
            "supportedRights": ["access", "portability", "erasure"],
            "subjectCoverageComplete": False,
            "erasureExecutable": False,
            "retentionPolicy": {
                "ready": False,
                "blocker": "policy_configuration_required",
            },
        }
        with mock.patch.object(
            rights_readiness.data_subject_rights,
            "capability",
            return_value={
                "bound": False,
                "partial": True,
                "supportedAdapters": {},
                "partialSystemAdapters": [],
            },
        ), mock.patch.object(
            rights_readiness.rights_subject_bindings,
            "rows",
            return_value=[],
        ), mock.patch.object(
            rights_readiness.rights_rectification,
            "capability",
            return_value={"partial": False},
        ), mock.patch.object(
            rights_readiness.mercure_rectification_boundary,
            "capability",
            return_value={},
        ), mock.patch.object(
            rights_readiness.referral_wallet_rights,
            "capability",
            return_value={"bound": False, "partial": True, "supportedRights": []},
        ), mock.patch.object(
            rights_readiness.withdrawal_readiness,
            "capability",
            return_value=withdrawal,
        ):
            state = rights_readiness.capability(self.db_path)

        self.assertFalse(state["bound"])
        self.assertEqual(state["withdrawalEvidenceExecution"], withdrawal)
        self.assertEqual(
            state["supportedAdapters"]["withdrawal_evidence"],
            ["access", "portability", "erasure"],
        )
        self.assertIn("withdrawal_evidence", state["partialSystemAdapters"])


if __name__ == "__main__":
    unittest.main()
