import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORKFLOW = ROOT / ".github/workflows/compliance-dpa-review-reconcile.yml"


class ComplianceDpaReviewReconcileWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_trigger_is_narrow_and_exact_main_guarded(self):
        self.assertIn("ops/compliance-dpa-review-reconcile", self.text)
        self.assertIn("refs/heads/ops/compliance-dpa-review-reconcile", self.text)
        self.assertIn("ops branch is not exact current main", self.text)
        self.assertIn("runtime revision does not match current main", self.text)
        self.assertNotIn("workflow_dispatch:", self.text)

    def test_transport_is_pinned_and_noninteractive(self):
        self.assertIn("checkupauto_planethoster_ed25519", self.text)
        self.assertIn("planethoster_known_hosts", self.text)
        self.assertIn("BatchMode=yes", self.text)
        self.assertIn("IdentitiesOnly=yes", self.text)
        self.assertIn("StrictHostKeyChecking=yes", self.text)
        self.assertNotIn("StrictHostKeyChecking=no", self.text)

    def test_transition_is_bounded_and_rollback_protected(self):
        self.assertIn("checkupauto-compliance-transition-dpa-review.py", self.text)
        self.assertIn('"--processor-id","autobilan_mercure"', self.text)
        self.assertIn("TRANSITION-PROCESSOR-DPA-REVIEW", self.text)
        self.assertIn("compliance-before-dpa-review-", self.text)
        self.assertIn("source.backup(target)", self.text)
        self.assertIn("backup_source.backup(runtime_target)", self.text)
        self.assertIn("processor_dpa_insufficient", self.text)
        self.assertIn("already_resolved", self.text)
        self.assertIn("signed DPA evidence missing", self.text)
        self.assertIn("CHECKUPAUTO_DPA_REVIEW_RECONCILE=", self.text)

    def test_workflow_does_not_embed_private_contract_material(self):
        self.assertNotIn("Contrat informatique.pdf", self.text)
        self.assertNotIn("CONTRAT MAINTENANCE 2022.pdf", self.text)
        self.assertNotIn("c3e53515b66aa8b29cd30a9a4be15a8fe45593a3f885a8912f5d06d402eb6169", self.text)


if __name__ == "__main__":
    unittest.main()
