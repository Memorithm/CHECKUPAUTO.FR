import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent
WORKFLOW=ROOT/".github/workflows/compliance-147-register-attestation.yml"


class Compliance147RegisterAttestationWorkflowTest(unittest.TestCase):
    def test_workflow_is_exact_main_and_exact_runtime_guarded(self):
        source=WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("ops/compliance-147-register-attestation",source)
        self.assertIn("ops branch is not exact current main",source)
        self.assertIn("runtime revision does not match current main",source)
        self.assertIn("StrictHostKeyChecking=yes",source)
        self.assertIn("IdentitiesOnly=yes",source)
        self.assertIn('venv_python="$release/.venv/bin/python"',source)
        self.assertIn('"$venv_python" - "$expected_sha"',source)
        self.assertNotIn("/opt/alt/python312/bin/python3 - \"$EXPECTED_SHA\"",source)

    def test_workflow_attests_only_exact_versioned_register_payload(self):
        source=WORKFLOW.read_text(encoding="utf-8")
        self.assertIn('fixtures/compliance-runtime-baseline.json',source)
        self.assertIn('runtime register differs from reviewed baseline',source)
        self.assertIn('expected_register_hash=digest',source)
        self.assertIn('"reviewedBaselineMatched":True',source)
        self.assertGreaterEqual(source.count('key=lambda row:str(row.get("id") or "")'),2)

    def test_workflow_preserves_dpa_fail_closed_gate(self):
        source=WORKFLOW.read_text(encoding="utf-8")
        self.assertIn('"processor_dpa_pending" not in blocker_types',source)
        self.assertIn('"readyForPublicContracting"',source)
        self.assertIn("compliance-before-register-attestation-",source)


if __name__=="__main__":
    unittest.main()
