"""GitHub-hosted Xcode runners must run real simulator tests, not silently skip."""
from pathlib import Path
import unittest

WORKFLOW = Path(__file__).resolve().parent / ".github/workflows/ios-core-ci.yml"


class IOSSimulatorQualificationTests(unittest.TestCase):
    def test_simulator_is_discovered_or_provisioned_before_test(self):
        script = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("xcrun simctl list devices available --json", script)
        self.assertIn("xcodebuild -downloadPlatform iOS", script)
        self.assertIn("xcrun simctl list runtimes --json", script)
        self.assertIn("xcrun simctl create", script)
        self.assertIn('test -n "$simulator_id"', script)
        self.assertIn('-destination "platform=iOS Simulator,id=$simulator_id"', script)
        self.assertIn("xcodebuild test -project CheckupAutoReminder.xcodeproj", script)
        self.assertNotIn("-destination 'platform=iOS Simulator,name=iPhone 16 Pro'", script)
        self.assertNotIn("|| true", script.split("xcodegen generate", 1)[1])


if __name__ == "__main__":
    unittest.main()
