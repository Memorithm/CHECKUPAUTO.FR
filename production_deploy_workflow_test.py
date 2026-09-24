from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent
WORKFLOW = ROOT / ".github" / "workflows" / "production-deploy.yml"


class ProductionDeployWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_approved_commit_is_validated_before_checkout_or_deploy(self):
        gate = self.workflow.index("- name: Validate signed main commit and Security CI")
        checkout = self.workflow.index("- name: Checkout approved main commit")
        deploy = self.workflow.index("- name: Deploy current approved main commit")
        verify = self.workflow.index("- name: Verify canonical public CyberCheck surface")
        self.assertLess(gate, checkout)
        self.assertLess(checkout, deploy)
        self.assertLess(deploy, verify)

    def test_checkout_is_exact_approved_sha_without_persisted_credentials(self):
        self.assertIn("uses: actions/checkout@v5", self.workflow)
        self.assertIn("ref: ${{ inputs.sha }}", self.workflow)
        self.assertIn("persist-credentials: false", self.workflow)

    def test_public_surface_probe_is_a_required_post_deploy_gate(self):
        self.assertIn(
            "run: python3 scripts/check-public-surface.py https://www.checkupauto.fr/",
            self.workflow,
        )
        self.assertNotIn("continue-on-error", self.workflow)

    def test_deployment_still_requires_exact_main_sha_and_green_push_security_ci(self):
        self.assertIn("Requested SHA is not the current GitHub main commit", self.workflow)
        self.assertIn("Requested main commit is not signature-verified by GitHub", self.workflow)
        self.assertIn(
            "No successful push Security CI exists for the requested main SHA",
            self.workflow,
        )


if __name__ == "__main__":
    unittest.main()
