import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import compliance_admin
import mercure_rectification_boundary


class ComplianceAdminMercureRectificationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "compliance.sqlite3"

    def tearDown(self):
        self.tmp.cleanup()

    def provider_env(self, fields="", evidence_sha256=""):
        return {
            mercure_rectification_boundary.PROVIDER_FIELDS_ENV: fields,
            mercure_rectification_boundary.PROVIDER_EVIDENCE_SHA256_ENV: evidence_sha256,
        }

    def test_unconfigured_rectification_is_visible_and_fail_closed(self):
        with mock.patch.dict(os.environ, self.provider_env(), clear=False):
            state = compliance_admin.snapshot(self.db)

        rectification = state["mercureRectification"]
        self.assertEqual(rectification["state"], "unverified")
        self.assertFalse(rectification["providerMutationCapabilityVerified"])
        self.assertFalse(rectification["completionEligible"])
        self.assertEqual(state["summary"]["mercureRectificationState"], "unverified")
        self.assertFalse(state["summary"]["mercureRectificationProviderAttested"])
        self.assertFalse(state["summary"]["mercureRectificationVerified"])

    def test_provider_attestation_is_visible_without_claiming_mutation_support(self):
        evidence_hash = "a" * 64
        with mock.patch.dict(
            os.environ,
            self.provider_env(fields="contact.email", evidence_sha256=evidence_hash),
            clear=False,
        ):
            state = compliance_admin.snapshot(self.db)

        rectification = state["mercureRectification"]
        self.assertEqual(rectification["state"], "provider_attested")
        self.assertTrue(rectification["providerMutationEvidence"]["attested"])
        self.assertEqual(rectification["providerMutationEvidence"]["fields"], ["contact.email"])
        self.assertEqual(rectification["providerMutationEvidence"]["evidenceSha256"], evidence_hash)
        self.assertEqual(rectification["verifiedAuthoritativeMutationFields"], [])
        self.assertFalse(rectification["providerMutationCapabilityVerified"])
        self.assertFalse(rectification["completionEligible"])
        self.assertTrue(state["summary"]["mercureRectificationProviderAttested"])
        self.assertFalse(state["summary"]["mercureRectificationVerified"])
        self.assertNotIn("provider contract body", repr(rectification))

    def test_invalid_provider_attestation_is_propagated(self):
        with mock.patch.dict(
            os.environ,
            self.provider_env(fields="contact.unknown", evidence_sha256="b" * 64),
            clear=False,
        ):
            state = compliance_admin.snapshot(self.db)

        rectification = state["mercureRectification"]
        self.assertEqual(rectification["state"], "invalid")
        self.assertEqual(
            rectification["reason"],
            "provider_rectification_fields_unsupported",
        )
        self.assertFalse(state["summary"]["mercureRectificationProviderAttested"])
        self.assertFalse(state["summary"]["mercureRectificationVerified"])

    def test_verified_state_requires_implementation_attestation_and_provider_verification(self):
        evidence_hash = "c" * 64
        with (
            mock.patch.dict(
                os.environ,
                self.provider_env(fields="contact.email", evidence_sha256=evidence_hash),
                clear=False,
            ),
            mock.patch.object(
                mercure_rectification_boundary,
                "VERIFIED_AUTHORITATIVE_MUTATION_FIELDS",
                ("contact.email",),
            ),
            mock.patch.object(
                mercure_rectification_boundary,
                "PROVIDER_BACKED_VERIFICATION_FIELDS",
                ("contact.email",),
            ),
        ):
            state = compliance_admin.snapshot(self.db)

        rectification = state["mercureRectification"]
        self.assertEqual(rectification["state"], "verified")
        self.assertTrue(rectification["providerMutationCapabilityVerified"])
        self.assertTrue(rectification["completionEligible"])
        self.assertEqual(state["summary"]["mercureRectificationState"], "verified")
        self.assertTrue(state["summary"]["mercureRectificationProviderAttested"])
        self.assertTrue(state["summary"]["mercureRectificationVerified"])


if __name__ == "__main__":
    unittest.main()
