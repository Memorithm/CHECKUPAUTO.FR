from pathlib import Path
import unittest


class AdminComplianceReviewUIContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = Path("admin/index.html").read_text(encoding="utf-8")
        cls.js = Path("admin/compliance.js").read_text(encoding="utf-8")

    def test_register_attestation_controls_are_present(self):
        for element_id in (
            "complianceRegisterReviewState",
            "complianceRegisterCurrentHash",
            "complianceRegisterAttestedHash",
            "complianceRegisterReviewedAt",
            "complianceRegisterReviewConfirm",
            "complianceRegisterAttest",
        ):
            self.assertIn(f'id="{element_id}"', self.html)
        self.assertIn("/api/admin/compliance/register-attestation", self.js)
        self.assertIn("expectedRegisterHash:$('#complianceRegisterCurrentHash').value", self.js)

    def test_processing_review_controls_use_displayed_activity_digest(self):
        for element_id in (
            "complianceProcessingReviewState",
            "complianceProcessingReviewRows",
            "complianceProcessingActivityId",
            "complianceProcessingExpectedHash",
            "complianceProcessingSecurityStatus",
            "complianceProcessingPrivacyStatus",
            "complianceProcessingEvidence",
            "complianceProcessingReviewSubmit",
        ):
            self.assertIn(f'id="{element_id}"', self.html)
        self.assertIn("/api/admin/compliance/processing-review", self.js)
        self.assertIn("expectedActivityHash:$('#complianceProcessingExpectedHash').value", self.js)
        self.assertIn("evidence:$('#complianceProcessingEvidence').value", self.js)

    def test_raw_review_evidence_is_not_rendered_from_snapshot(self):
        self.assertNotIn("sourceEvidence", self.html)
        self.assertNotIn("reviewEvidence", self.html)
        self.assertNotIn("esc(row.evidence)", self.js)
        self.assertNotIn("row.rawEvidence", self.js)


if __name__ == "__main__":
    unittest.main()
