from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent
WORKFLOW = ROOT / ".github" / "workflows" / "ios-testflight.yml"
CREDENTIALS = ROOT / "scripts" / "checkupauto-testflight-credentials.sh"

class TestFlightWorkflowStructureTest(unittest.TestCase):
    def test_external_gate_is_output_driven_and_non_red(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("id: apple", text)
        self.assertIn("steps.apple.outputs.ready != 'true'", text)
        self.assertIn("steps.apple.outputs.ready == 'true'", text)
        self.assertIn("TESTFLIGHT_BLOCKED_EXTERNAL=app-store-connect-team-key", text)
        self.assertEqual(text.count("- name: Build, sign and upload to TestFlight"), 1)
        self.assertEqual(text.count("- name: Clean temporary release material"), 1)

    def test_credential_probe_is_external_script(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("scripts/checkupauto-testflight-credentials.sh", text)
        self.assertTrue(CREDENTIALS.is_file())

if __name__ == "__main__":
    unittest.main()
