from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent
WORKFLOW = ROOT / ".github" / "workflows" / "ios-testflight.yml"
CREDENTIALS = ROOT / "scripts" / "checkupauto-testflight-credentials.sh"


class IOSTestFlightWorkflowTest(unittest.TestCase):
    def test_missing_external_team_key_is_reported_without_upload(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("scripts/checkupauto-testflight-credentials.sh", text)
        self.assertIn("id: apple", text)
        self.assertIn("steps.apple.outputs.ready != 'true'", text)
        self.assertIn("steps.apple.outputs.ready == 'true'", text)
        self.assertIn("Report external Apple credential gate", text)
        self.assertIn("TESTFLIGHT_BLOCKED_EXTERNAL=app-store-connect-team-key", text)

    def test_workflow_has_one_upload_and_one_cleanup_block(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertEqual(text.count("- name: Build, sign and upload to TestFlight"), 1)
        self.assertEqual(text.count("- name: Clean temporary release material"), 1)
        self.assertEqual(text.count("- name: Report external Apple credential gate"), 1)
        self.assertEqual(text.count("- name: Resolve Apple release state"), 1)

    def test_credential_helper_distinguishes_missing_from_invalid_state(self):
        text = CREDENTIALS.read_text(encoding="utf-8")
        self.assertIn("ready=false", text)
        self.assertIn("ready=true", text)
        self.assertIn("credential_error=provisioning_team_not_unique", text)
        self.assertIn("credential_error=app_store_key_not_unique", text)
        self.assertIn("credential_error=issuer_missing", text)
        self.assertIn("credential_error=issuer_invalid", text)
        self.assertIn("credential_error=unsafe_permissions", text)
        self.assertIn("credential_error=key_format_invalid", text)
        self.assertIn("exit 2", text)

    def test_credential_helper_keeps_private_material_on_mac(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        helper = CREDENTIALS.read_text(encoding="utf-8")
        self.assertNotIn("CHECKUPAUTO_ASC_KEY_P8", workflow)
        self.assertIn("key_path=%s", helper)
        self.assertIn('vault="$HOME/Library/Application Support/CheckupAuto/AppStoreConnect"', helper)
        self.assertNotIn("cat "$key_path"", helper)


if __name__ == "__main__":
    unittest.main()
