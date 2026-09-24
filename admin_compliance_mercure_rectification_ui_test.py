import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parent
SCRIPT = (ROOT / "admin" / "compliance.js").read_text(encoding="utf-8")


class ComplianceMercureRectificationUiTest(unittest.TestCase):
    def test_console_renders_rectification_state_independently(self):
        self.assertIn("snapshot?.mercureRectification", SCRIPT)
        self.assertIn("mercureRectificationStateLabel", SCRIPT)
        self.assertIn("VÉRIFIÉ", SCRIPT)
        self.assertIn("ATTESTÉ FOURNISSEUR", SCRIPT)
        self.assertIn("INVALIDE", SCRIPT)
        self.assertIn("NON VÉRIFIÉ", SCRIPT)
        self.assertIn("Rectification autoritaire Mercure", SCRIPT)

    def test_provider_attestation_alone_cannot_render_verified(self):
        self.assertIn("providerMutationCapabilityVerified===true", SCRIPT)
        self.assertIn("rectification.completionEligible===true", SCRIPT)
        self.assertIn("rectificationState==='verified'", SCRIPT)
        self.assertIn("provider_attested", SCRIPT)
        self.assertIn("Une preuve fournisseur seule ne constitue jamais", SCRIPT)

    def test_console_shows_only_bounded_hashed_evidence(self):
        self.assertIn("rectification.providerMutationEvidence", SCRIPT)
        self.assertIn("rectification.verifiedAuthoritativeMutationFields", SCRIPT)
        self.assertIn("rectification.providerBackedVerificationFields", SCRIPT)
        self.assertIn("PREUVE RECTIFICATION SHA-256", SCRIPT)
        self.assertIn("esc(rectificationEvidence)", SCRIPT)
        self.assertNotIn("CYBERCHECK_MERCURE_RECTIFICATION_EVIDENCE_SHA256", SCRIPT)

    def test_dynamic_rectification_values_are_escaped(self):
        self.assertIn("esc(rectificationAttestedFields.join(', ')||'Aucun')", SCRIPT)
        self.assertIn("esc(rectificationMutationFields.join(', ')||'Aucun')", SCRIPT)
        self.assertIn("esc(rectificationVerificationFields.join(', ')||'Aucun')", SCRIPT)
        self.assertIn("esc(rectificationReason)", SCRIPT)


if __name__ == "__main__":
    unittest.main()
