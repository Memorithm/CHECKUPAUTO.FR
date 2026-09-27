from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent
WORKFLOW = ROOT / ".github" / "workflows" / "staging-deploy.yml"


class StagingDeployWorkflowTest(unittest.TestCase):
    def test_staging_is_isolated_from_production(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("STAGING_DOMAIN: test-v3.checkupauto.fr", text)
        self.assertIn("STAGING_PRIVATE_ROOT: .checkupauto-staging-v3", text)
        self.assertIn("STAGING_WEB_ROOT: test-v3.checkupauto.fr", text)
        self.assertNotIn("STAGING_WEB_ROOT: public_html", text)
        self.assertNotIn("STAGING_PRIVATE_ROOT: .checkupauto\n", text)

    def test_workflow_uses_dedicated_key_and_strict_host_checking(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("/opt/actions-runner/.ssh/checkupauto_planethoster_ed25519", text)
        self.assertIn("StrictHostKeyChecking=yes", text)
        self.assertIn("IdentitiesOnly=yes", text)
        self.assertNotIn("sshpass", text)
        self.assertNotIn("PLANETHOSTER_PASSWORD", text)

    def test_install_and_update_require_current_green_main(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn('if action in {"install", "update"}:', text)
        self.assertIn('get("/branches/main")', text)
        self.assertIn('"/actions/workflows/security-ci.yml/runs"', text)
        self.assertIn('run.get("conclusion") == "success"', text)

    def test_green_main_security_run_updates_staging_exact_sha(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("workflow_run:", text)
        self.assertIn("- Security CI", text)
        self.assertIn("github.event.workflow_run.conclusion == 'success'", text)
        self.assertIn("github.event.workflow_run.event == 'push'", text)
        self.assertIn("github.event.workflow_run.head_branch == 'main'", text)
        self.assertIn("github.event_name == 'workflow_dispatch' && inputs.action || 'update'", text)
        self.assertIn("github.event.workflow_run.head_sha", text)
        self.assertIn("github.event_name == 'workflow_run'", text)

    def test_admin_password_is_runner_local_not_repository_secret(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("/opt/actions-runner/.checkupauto-staging-admin-password", text)
        self.assertIn("CYBERCHECK_DEPLOY_ADMIN_PASSWORD_FILE", text)
        self.assertNotIn("BEGIN OPENSSH PRIVATE KEY", text)


if __name__ == "__main__":
    unittest.main()
