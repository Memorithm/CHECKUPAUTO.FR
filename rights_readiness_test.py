from __future__ import annotations

import unittest
from unittest import mock

import rights_readiness


class RightsReadinessTest(unittest.TestCase):
    def _wallet(self):
        return {
            "bound": True,
            "partial": True,
            "adapter": "referral_wallet",
            "supportedRights": ["access", "portability"],
            "ownershipProvenance": "authenticated_mobile_wallet_claim",
            "ownerEvidenceCount": 1,
            "remainingOperations": ["rectification_policy", "erasure_retention_policy"],
        }

    def test_capability_reports_all_implemented_binding_paths(self):
        with mock.patch.object(
            rights_readiness.data_subject_rights,
            "capability",
            return_value={
                "bound": False,
                "partial": True,
                "subjectBindingProvenance": ["mobile_vehicle_binding"],
                "supportedAdapters": {},
                "partialSystemAdapters": [],
            },
        ), mock.patch.object(
            rights_readiness.rights_subject_bindings,
            "rows",
            return_value=[],
        ), mock.patch.object(
            rights_readiness.referral_wallet_rights,
            "capability",
            return_value=self._wallet(),
        ):
            state = rights_readiness.capability()

        self.assertEqual(
            state["subjectBindingProvenance"],
            ["mobile_vehicle_binding", "mercure_appointment"],
        )
        self.assertEqual(state["observedSubjectBindingProvenance"], [])
        self.assertFalse(state["subjectBindingEvidenceObserved"])
        self.assertFalse(state["bound"])
        self.assertTrue(state["partial"])
        self.assertEqual(
            state["supportedAdapters"]["referral_wallet"],
            ["access", "portability"],
        )
        self.assertIn("referral_wallet", state["partialSystemAdapters"])
        self.assertTrue(state["referralWalletExecution"]["bound"])

    def test_observed_provenance_is_aggregated_without_raw_binding_rows(self):
        sensitive = "account:must-not-surface"
        with mock.patch.object(
            rights_readiness.data_subject_rights,
            "capability",
            return_value={"bound": False, "partial": True},
        ), mock.patch.object(
            rights_readiness.rights_subject_bindings,
            "rows",
            return_value=[
                {
                    "requestId": "a" * 32,
                    "adapter": "mercure_customer_contact",
                    "provenance": "mobile_vehicle_binding",
                    "subjectRef": sensitive,
                },
                {
                    "requestId": "b" * 32,
                    "adapter": "compliance_contracts",
                    "provenance": "mercure_appointment",
                    "subjectRef": sensitive,
                },
            ],
        ), mock.patch.object(
            rights_readiness.referral_wallet_rights,
            "capability",
            return_value=self._wallet(),
        ):
            state = rights_readiness.capability()

        self.assertEqual(
            state["observedSubjectBindingProvenance"],
            ["mercure_appointment", "mobile_vehicle_binding"],
        )
        self.assertTrue(state["subjectBindingEvidenceObserved"])
        self.assertNotIn(sensitive, str(state))
        self.assertNotIn("requestId", state)

    def test_wallet_readiness_failure_is_fail_closed(self):
        with mock.patch.object(
            rights_readiness.data_subject_rights,
            "capability",
            return_value={"bound": False, "partial": True},
        ), mock.patch.object(
            rights_readiness.rights_subject_bindings,
            "rows",
            return_value=[],
        ), mock.patch.object(
            rights_readiness.referral_wallet_rights,
            "capability",
            side_effect=RuntimeError("database path should not leak"),
        ):
            state = rights_readiness.capability()

        wallet = state["referralWalletExecution"]
        self.assertFalse(wallet["bound"])
        self.assertEqual(wallet["state"], "unavailable")
        self.assertNotIn("database path should not leak", str(wallet))
        self.assertFalse(state["bound"])


if __name__ == "__main__":
    unittest.main()
