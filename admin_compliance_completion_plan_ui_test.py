from pathlib import Path
import unittest


class AdminComplianceCompletionPlanUIContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.js = Path("admin/compliance.js").read_text(encoding="utf-8")

    def test_console_reads_bounded_completion_plan_snapshot(self):
        self.assertIn("snapshot?.rightsCompletion?.plans", self.js)
        for field in (
            "knownScopeComplete",
            "globalCoverageComplete",
            "executionComplete",
            "executionLimitation",
            "justificationHash",
            "satisfied",
        ):
            self.assertIn(field, self.js)

    def test_open_requests_expose_plan_action(self):
        self.assertIn("compliance-plan-right", self.js)
        self.assertIn("Planifier", self.js)
        self.assertIn("editRightsPlan(b.dataset.id)", self.js)

    def test_executed_adapter_is_kept_required(self):
        self.assertIn("if(item.executed)", self.js)
        self.assertIn("entries.push({adapter:item.adapter,disposition:'required'})", self.js)

    def test_not_applicable_requires_fresh_justification(self):
        self.assertIn("disposition==='not_applicable'", self.js)
        self.assertIn("justification:justification.trim()", self.js)
        self.assertIn("Elle sera hachée côté serveur et ne sera pas conservée en clair", self.js)

    def test_plan_posts_exact_request_plan_shape(self):
        self.assertIn(
            "await api('/api/admin/compliance/request-plan',{id:requestId,entries:entries})",
            self.js,
        )

    def test_console_does_not_expose_request_closure_mutation(self):
        self.assertNotIn("/api/admin/compliance/request-close", self.js)
        self.assertNotIn("closureReady:true", self.js)


if __name__ == "__main__":
    unittest.main()
