import unittest
from unittest.mock import Mock, patch

import mercure_admin_client
import mercure_rectification_boundary
import rights_readiness


class MercureRectificationBoundaryTest(unittest.TestCase):
    def test_synthetic_appointment_writes_are_not_promoted_to_rectification(self):
        self.assertTrue(callable(mercure_admin_client.create_synthetic_test_appointment))
        self.assertTrue(callable(mercure_admin_client.remove_synthetic_test_appointment))

        result = mercure_rectification_boundary.capability()

        self.assertEqual(result["provider"], "mercure")
        self.assertEqual(result["state"], "unverified")
        self.assertEqual(result["verifiedAuthoritativeMutationFields"], [])
        self.assertFalse(result["applicationMutationPrimitiveImplemented"])
        self.assertFalse(result["providerMutationCapabilityVerified"])
        self.assertFalse(result["completionEligible"])
        self.assertFalse(result["syntheticAppointmentWritesCountAsRectificationEvidence"])
        self.assertEqual(
            result["observedNonRectificationWrites"],
            ["synthetic_appointment_create", "synthetic_appointment_remove"],
        )
        self.assertEqual(result["reason"], "no_verified_provider_rectification_primitive")

    def test_method_name_alone_cannot_infer_authoritative_write_capability(self):
        with patch.object(
            mercure_admin_client,
            "update_vehicle_due_date",
            Mock(),
            create=True,
        ):
            result = mercure_rectification_boundary.capability()

        self.assertFalse(result["providerMutationCapabilityVerified"])
        self.assertFalse(result["completionEligible"])
        self.assertEqual(result["verifiedAuthoritativeMutationFields"], [])

    @patch.object(rights_readiness, "_wallet_capability", return_value={"bound": False})
    @patch.object(rights_readiness.rights_rectification, "capability", return_value={"partial": False})
    @patch.object(rights_readiness.rights_subject_bindings, "rows", return_value=[])
    @patch.object(
        rights_readiness.data_subject_rights,
        "capability",
        return_value={"bound": False, "supportedAdapters": {}},
    )
    def test_readiness_exposes_fail_closed_provider_boundary(
        self, _central, _bindings, _rectification, _wallet
    ):
        result = rights_readiness.capability()

        provider = result["mercureRectification"]
        self.assertEqual(provider["state"], "unverified")
        self.assertFalse(provider["completionEligible"])
        self.assertEqual(provider["verifiedAuthoritativeMutationFields"], [])


if __name__ == "__main__":
    unittest.main()
