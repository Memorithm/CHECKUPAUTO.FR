import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parent
SCRIPT = (ROOT / "admin" / "compliance.js").read_text(encoding="utf-8")


class ComplianceWithdrawalReadinessUiTest(unittest.TestCase):
    def test_console_reads_runtime_withdrawal_erasure_readiness(self):
        self.assertIn(
            "snapshot?.dataSubjectExecution?.withdrawalEvidenceExecution",
            SCRIPT,
        )
        self.assertIn("execution.erasureExecutable===true", SCRIPT)
        self.assertIn("execution.erasureImplemented===true", SCRIPT)
        self.assertIn("policy.configured===true", SCRIPT)
        self.assertIn("policy.enabled===true", SCRIPT)
        self.assertIn("policy.legalReviewConfirmed===true", SCRIPT)
        self.assertIn("policy.activeDays", SCRIPT)
        self.assertIn("policy.blocker", SCRIPT)

    def test_widget_is_fail_closed_and_distinguishes_subject_coverage(self):
        self.assertIn("EXÉCUTABLE", SCRIPT)
        self.assertIn("BLOQUÉ", SCRIPT)
        self.assertIn("VALIDATION JURIDIQUE", SCRIPT)
        self.assertIn("COUVERTURE SUJET", SCRIPT)
        self.assertIn("execution.subjectCoverageComplete===true?'COMPLÈTE':'PARTIELLE'", SCRIPT)
        self.assertIn("Validation juridique requise", SCRIPT)
        self.assertIn("Politique indisponible", SCRIPT)
        self.assertIn("Blocage non classé", SCRIPT)

    def test_widget_uses_dom_text_nodes_and_does_not_render_raw_retention_justification(self):
        self.assertIn("#complianceWithdrawalErasureReadiness", SCRIPT)
        self.assertIn("box.replaceChildren()", SCRIPT)
        self.assertIn("status.textContent", SCRIPT)
        self.assertIn("small.textContent=label", SCRIPT)
        self.assertIn("strong.textContent=value", SCRIPT)
        self.assertNotIn("policy.justification", SCRIPT)
        self.assertNotIn("retentionPolicy.justification", SCRIPT)
        self.assertIn("renderWithdrawalErasureReadiness();", SCRIPT)


if __name__ == "__main__":
    unittest.main()
