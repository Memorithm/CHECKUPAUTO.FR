from pathlib import Path
import unittest

WORKFLOW=Path(__file__).parent/".github/workflows/compliance-147-known-identity.yml"

class Compliance147KnownIdentityWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text=WORKFLOW.read_text(encoding="utf-8")

    def test_operation_is_exact_main_and_exact_runtime_only(self):
        self.assertIn("ops/compliance-147-known-identity",self.text)
        self.assertIn("ops branch is not exact current main",self.text)
        self.assertIn("runtime revision does not match current main",self.text)
        self.assertIn('test "$(git rev-parse HEAD)" = "$EXPECTED_SHA"',self.text)

    def test_mutation_is_backed_up_and_conflict_safe(self):
        self.assertIn("compliance-before-known-identity-",self.text)
        self.assertIn("source.backup(target)",self.text)
        self.assertIn("backup_source.backup(runtime_target)",self.text)
        self.assertIn("APPLY-KNOWN-IDENTITY-FACTS",self.text)
        self.assertIn('expected_missing=[]',self.text)
        self.assertIn("known identity apply failed and backup restored",self.text)

    def test_transport_is_pinned_and_output_is_bounded(self):
        self.assertIn("StrictHostKeyChecking=yes",self.text)
        self.assertIn("IdentitiesOnly=yes",self.text)
        self.assertIn("BatchMode=yes",self.text)
        self.assertIn("CHECKUPAUTO_COMPLIANCE_147_IDENTITY=",self.text)
        self.assertNotIn('"privacyContact":',self.text)
        self.assertNotIn('"mediatorName":',self.text)
        self.assertNotIn('"mediatorUrl":',self.text)

if __name__=="__main__":
    unittest.main()
