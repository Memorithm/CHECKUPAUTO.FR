from pathlib import Path
import unittest


ROOT=Path(__file__).resolve().parent
WORKFLOW=ROOT/".github/workflows/planethoster-test-current-main.yml"


class PlanetHosterCurrentMainControlPlaneTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text=WORKFLOW.read_text(encoding="utf-8")

    def test_application_repo_has_no_privileged_planethoster_job(self):
        self.assertIn("name: PlanetHoster deployment ownership contract",self.text)
        self.assertIn("PLANETHOSTER_DEPLOYMENT_OWNER=Memorithm/RemoteOps",self.text)
        self.assertNotIn("workflow_run:",self.text)
        self.assertNotIn("checkupauto-planethoster-legacy-staging-deploy.py",self.text)
        self.assertNotIn("STAGING_KEY",self.text)
        self.assertNotIn("STAGING_KNOWN_HOSTS",self.text)

    def test_application_repo_never_targets_remoteops_control_runner(self):
        self.assertNotIn("remoteops, mac-mini",self.text)
        self.assertNotIn("remoteops, thor",self.text)
        self.assertIn("runs-on: [self-hosted, Linux, ARM64, internal]",self.text)


if __name__=="__main__":
    unittest.main()
