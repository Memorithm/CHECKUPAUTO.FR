from pathlib import Path
import unittest


ROOT=Path(__file__).resolve().parent
WORKFLOW=ROOT/".github/workflows/planethoster-test-current-main.yml"


class PlanetHosterCurrentMainWorkflowTest(unittest.TestCase):
    def test_workflow_is_contract_only(self):
        text=WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:",text)
        self.assertIn("PLANETHOSTER_DEPLOYMENT_OWNER=Memorithm/RemoteOps",text)
        self.assertNotIn("workflow_run:",text)
        self.assertNotIn("ssh ",text)
        self.assertNotIn("sudo ",text)
        self.assertNotIn("nodels49-eu.n0c.com",text)

    def test_no_hosting_credentials_are_referenced(self):
        text=WORKFLOW.read_text(encoding="utf-8")
        self.assertNotIn(".ssh/",text)
        self.assertNotIn("checkupauto_planethoster",text)
        self.assertNotIn("planethoster_known_hosts",text)


if __name__=="__main__":
    unittest.main()
