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
        verify = self.workflow.index("- name: Verify deployed runtime health and revision")
        self.assertLess(gate, checkout)
        self.assertLess(checkout, deploy)
        self.assertLess(deploy, verify)

    def test_checkout_is_exact_approved_sha_without_persisted_credentials(self):
        self.assertIn("uses: actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09 # v5.1.0", self.workflow)
        self.assertIn("ref: ${{ inputs.sha }}", self.workflow)
        self.assertIn("persist-credentials: false", self.workflow)

    def test_runtime_health_and_revision_probe_is_a_required_post_deploy_gate(self):
        self.assertIn("DEPLOY_SHA: ${{ inputs.sha }}", self.workflow)
        self.assertGreaterEqual(
            self.workflow.count('sudo -n /usr/local/sbin/cybercheck-deploy "$DEPLOY_SHA"'),
            2,
        )
        self.assertIn("- name: Verify deployed runtime health and revision", self.workflow)
        self.assertNotIn("check-public-surface.py https://www.checkupauto.fr/", self.workflow)
        self.assertNotIn("continue-on-error", self.workflow)

    def test_deploy_job_is_pinned_to_dedicated_trusted_checkupauto_runner(self):
        self.assertIn(
            "runs-on: [self-hosted, Linux, ARM64, internal, checkupauto-ci, trusted-main]",
            self.workflow,
        )

    def test_deployment_still_requires_exact_main_sha_and_green_push_security_ci(self):
        self.assertIn("Requested SHA is not the current GitHub main commit", self.workflow)
        self.assertIn("Requested main commit is not signature-verified by GitHub", self.workflow)
        self.assertIn(
            "No successful push Security CI exists for the requested main SHA",
            self.workflow,
        )


if __name__ == "__main__":
    unittest.main()
