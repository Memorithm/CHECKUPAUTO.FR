import os
import unittest
from unittest.mock import Mock, patch

import mercure_admin_client
import mercure_rectification_boundary
import rights_readiness


class MercureRectificationBoundaryTest(unittest.TestCase):
    def _no_provider_evidence(self):
        return patch.dict(
            os.environ,
            {
                mercure_rectification_boundary.PROVIDER_FIELDS_ENV: "",
                mercure_rectification_boundary.PROVIDER_EVIDENCE_SHA256_ENV: "",
            },
        )

    def test_synthetic_appointment_writes_are_not_promoted_to_rectification(self):
        self.assertTrue(callable(mercure_admin_client.create_synthetic_test_appointment))
        self.assertTrue(callable(mercure_admin_client.remove_synthetic_test_appointment))

        with self._no_provider_evidence():
            result = mercure_rectification_boundary.capability()

        self.assertEqual(result["provider"], "mercure")
        self.assertEqual(result["state"], "unverified")
        self.assertEqual(result["verifiedAuthoritativeMutationFields"], [])
        self.assertEqual(result["providerBackedVerificationFields"], [])
        self.assertFalse(result["applicationMutationPrimitiveImplemented"])
        self.assertFalse(result["providerMutationCapabilityVerified"])
        self.assertFalse(result["completionEligible"])
        self.assertFalse(result["syntheticAppointmentWritesCountAsRectificationEvidence"])
        self.assertEqual(
            result["observedNonRectificationWrites"],
            ["synthetic_appointment_create", "synthetic_appointment_remove"],
        )
        self.assertEqual(result["providerMutationEvidence"]["state"], "unconfigured")
        self.assertEqual(result["reason"], "no_verified_provider_rectification_primitive")

    def test_method_name_alone_cannot_infer_authoritative_write_capability(self):
        with self._no_provider_evidence(), patch.object(
            mercure_admin_client,
            "update_vehicle_due_date",
            Mock(),
            create=True,
        ):
            result = mercure_rectification_boundary.capability()

        self.assertFalse(result["providerMutationCapabilityVerified"])
        self.assertFalse(result["completionEligible"])
        self.assertEqual(result["verifiedAuthoritativeMutationFields"], [])

    def test_external_provider_evidence_alone_does_not_promote_completion(self):
        evidence = "a" * 64
        with patch.dict(
            os.environ,
            {
                mercure_rectification_boundary.PROVIDER_FIELDS_ENV: "vehicle.technicalInspectionDueDate,contact.email",
                mercure_rectification_boundary.PROVIDER_EVIDENCE_SHA256_ENV: evidence,
            },
        ):
            result = mercure_rectification_boundary.capability()

        self.assertEqual(result["state"], "provider_attested")
        self.assertTrue(result["providerMutationEvidence"]["attested"])
        self.assertEqual(
            result["providerMutationEvidence"]["fields"],
            ["vehicle.technicalInspectionDueDate", "contact.email"],
        )
        self.assertEqual(result["providerMutationEvidence"]["evidenceSha256"], evidence)
        self.assertFalse(result["applicationMutationPrimitiveImplemented"])
        self.assertFalse(result["providerMutationCapabilityVerified"])
        self.assertFalse(result["completionEligible"])
        self.assertFalse(result["rawEvidenceStoredInRepository"])

    def test_invalid_or_unsupported_provider_evidence_fails_closed(self):
        with patch.dict(
            os.environ,
            {
                mercure_rectification_boundary.PROVIDER_FIELDS_ENV: "customer.unknownField",
                mercure_rectification_boundary.PROVIDER_EVIDENCE_SHA256_ENV: "b" * 64,
            },
        ):
            unsupported = mercure_rectification_boundary.capability()
        self.assertEqual(unsupported["state"], "invalid")
        self.assertEqual(unsupported["reason"], "provider_rectification_fields_unsupported")
        self.assertFalse(unsupported["completionEligible"])

        with patch.dict(
            os.environ,
            {
                mercure_rectification_boundary.PROVIDER_FIELDS_ENV: "contact.email",
                mercure_rectification_boundary.PROVIDER_EVIDENCE_SHA256_ENV: "not-a-sha256",
            },
        ):
            invalid_hash = mercure_rectification_boundary.capability()
        self.assertEqual(invalid_hash["state"], "invalid")
        self.assertEqual(invalid_hash["reason"], "provider_rectification_evidence_hash_invalid")
        self.assertFalse(invalid_hash["completionEligible"])

    def test_implementation_still_requires_provider_backed_verification(self):
        field = "vehicle.technicalInspectionDueDate"
        with patch.dict(
            os.environ,
            {
                mercure_rectification_boundary.PROVIDER_FIELDS_ENV: field,
                mercure_rectification_boundary.PROVIDER_EVIDENCE_SHA256_ENV: "c" * 64,
            },
        ), patch.object(
            mercure_rectification_boundary,
            "VERIFIED_AUTHORITATIVE_MUTATION_FIELDS",
            (field,),
        ):
            result = mercure_rectification_boundary.capability()

        self.assertTrue(result["applicationMutationPrimitiveImplemented"])
        self.assertFalse(result["providerMutationCapabilityVerified"])
        self.assertFalse(result["completionEligible"])
        self.assertEqual(result["reason"], "provider_backed_verification_incomplete")

    def test_completion_requires_evidence_implementation_and_provider_verification(self):
        field = "vehicle.technicalInspectionDueDate"
        with patch.dict(
            os.environ,
            {
                mercure_rectification_boundary.PROVIDER_FIELDS_ENV: field,
                mercure_rectification_boundary.PROVIDER_EVIDENCE_SHA256_ENV: "d" * 64,
            },
        ), patch.object(
            mercure_rectification_boundary,
            "VERIFIED_AUTHORITATIVE_MUTATION_FIELDS",
            (field,),
        ), patch.object(
            mercure_rectification_boundary,
            "PROVIDER_BACKED_VERIFICATION_FIELDS",
            (field,),
        ):
            result = mercure_rectification_boundary.capability()

        self.assertEqual(result["state"], "verified")
        self.assertTrue(result["providerMutationCapabilityVerified"])
        self.assertTrue(result["completionEligible"])
        self.assertEqual(result["reason"], "")

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
        with self._no_provider_evidence():
            result = rights_readiness.capability()

        provider = result["mercureRectification"]
        self.assertEqual(provider["state"], "unverified")
        self.assertFalse(provider["completionEligible"])
        self.assertEqual(provider["verifiedAuthoritativeMutationFields"], [])


if __name__ == "__main__":
    unittest.main()
