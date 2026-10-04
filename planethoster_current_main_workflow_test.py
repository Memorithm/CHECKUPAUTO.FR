from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parent
class PlanetHosterCurrentMainWorkflowTest(unittest.TestCase):
 def test_workflow_is_security_ci_gated_and_exact_main_only(self):
  text=(ROOT/".github/workflows/planethoster-test-current-main.yml").read_text()
  self.assertIn('workflows: ["Security CI"]',text)
  self.assertIn("github.event.workflow_run.conclusion == 'success'",text)
  self.assertIn("github.event.workflow_run.event == 'push'",text)
  self.assertIn("branches/main",text)
  self.assertIn("stale deployment refused",text)
 def test_workflow_uses_existing_dedicated_key_and_strict_deployer(self):
  text=(ROOT/".github/workflows/planethoster-test-current-main.yml").read_text()
  self.assertIn("/opt/actions-runner/.ssh/checkupauto_planethoster_ed25519",text)
  self.assertIn("/opt/actions-runner/.ssh/planethoster_known_hosts",text)
  self.assertIn("checkupauto-planethoster-legacy-staging-deploy.py",text)
  self.assertNotIn("StrictHostKeyChecking=no",text)
if __name__=="__main__": unittest.main()
