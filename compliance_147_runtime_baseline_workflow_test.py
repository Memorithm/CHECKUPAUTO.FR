from pathlib import Path
import unittest

WORKFLOW=Path(__file__).parent/".github/workflows/compliance-147-runtime-baseline.yml"

class Compliance147RuntimeBaselineWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text=WORKFLOW.read_text(encoding="utf-8")

    def test_trigger_is_narrow_and_requires_exact_current_main(self):
        self.assertIn("ops/compliance-147-runtime-baseline",self.text)
        self.assertNotIn("github.actor ==",self.text)
        self.assertIn("ops branch is not exact current main",self.text)
        self.assertIn('test "$(git rev-parse HEAD)" = "$EXPECTED_SHA"',self.text)

    def test_planethoster_transport_is_pinned_and_noninteractive(self):
        self.assertIn("/opt/actions-runner/.ssh/checkupauto_planethoster_ed25519",self.text)
        self.assertIn("/opt/actions-runner/.ssh/planethoster_known_hosts",self.text)
        self.assertIn("StrictHostKeyChecking=yes",self.text)
        self.assertIn("IdentitiesOnly=yes",self.text)
        self.assertIn("BatchMode=yes",self.text)
        self.assertNotIn("StrictHostKeyChecking=no",self.text)

    def test_runtime_mutation_is_one_shot_backed_up_and_bounded(self):
        self.assertIn("runtime revision does not match current main",self.text)
        self.assertIn("compliance-before-runtime-baseline-",self.text)
        self.assertIn("source.backup(target)",self.text)
        self.assertIn("backup_source.backup(runtime_target)",self.text)
        self.assertIn("backup restored",self.text)
        self.assertIn("already_initialized",self.text)
        self.assertIn("APPLY-REVIEWED-COMPLIANCE-BASELINE",self.text)
        self.assertIn('seed_result.get("blockerTypes")!=["processor_dpa_pending"]',self.text)
        self.assertIn("CHECKUPAUTO_COMPLIANCE_147=",self.text)
        self.assertNotIn("cat compliance.sqlite3",self.text)

if __name__=="__main__":
    unittest.main()
