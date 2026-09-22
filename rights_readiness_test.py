from __future__ import annotations

import unittest
from unittest import mock

import rights_readiness


class RightsReadinessTest(unittest.TestCase):
    def test_capability_reports_all_implemented_binding_paths(self):
        with mock.patch.object(
            rights_readiness.data_subject_rights,
            "capability",
            return_value={
                "bound": False,
                "partial": True,
                "subjectBindingProvenance": ["mobile_vehicle_binding"],
            },
        ), mock.patch.object(
            rights_readiness.rights_subject_bindings,
            "rows",
            return_value=[],
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
        ):
            state = rights_readiness.capability()

        self.assertEqual(
            state["observedSubjectBindingProvenance"],
            ["mercure_appointment", "mobile_vehicle_binding"],
        )
        self.assertTrue(state["subjectBindingEvidenceObserved"])
        self.assertNotIn(sensitive, str(state))
        self.assertNotIn("requestId", state)


if __name__ == "__main__":
    unittest.main()
