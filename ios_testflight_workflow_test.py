from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent
WORKFLOW = ROOT / ".github" / "workflows" / "ios-testflight.yml"


class IOSTestFlightWorkflowTest(unittest.TestCase):
    def test_missing_external_team_key_does_not_red_main_ci(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("CHECKUPAUTO_TESTFLIGHT_READY=0", text)
        self.assertIn("TestFlight upload blocked externally", text)
        self.assertIn("if: env.CHECKUPAUTO_TESTFLIGHT_READY == '1'", text)
        self.assertIn("Report TestFlight external prerequisite", text)
        self.assertIn("TESTFLIGHT_BLOCKED_EXTERNAL=app-store-connect-team-key", text)

    def test_partial_or_invalid_credentials_still_fail_closed(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("App Store Connect API credentials are partially configured", text)
        self.assertIn("Configured Apple Team ID does not match", text)
        self.assertIn("Resolved App Store Connect Key ID is invalid", text)
        self.assertIn("Resolved App Store Connect Issuer ID is invalid", text)


if __name__ == "__main__":
    unittest.main()
