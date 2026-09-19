import plistlib
import re
import unittest
from pathlib import Path


class IOSProjectManifestTest(unittest.TestCase):
    def setUp(self):
        self.path = Path("ios/CheckupAutoReminder/project.yml")
        self.text = self.path.read_text()

    def test_xctest_target_excludes_smoke_entry_points(self):
        match = re.search(
            r"  CheckupAutoReminderTests:\n(?P<body>.*?)(?=\n  [A-Za-z0-9_-]+:|\Z)",
            self.text,
            flags=re.S,
        )
        self.assertIsNotNone(match, "CheckupAutoReminderTests target missing")
        body = match.group("body")
        for smoke in (
            "ReminderPlanSmoke.swift",
            "MobileBootstrapSmoke.swift",
            "MobileDeadlineSyncSmoke.swift",
        ):
            self.assertNotIn(smoke, body)

    def test_app_enables_only_checkupauto_associated_domain(self):
        entitlements = plistlib.loads(
            Path("ios/CheckupAutoReminder/CheckupAutoReminder.entitlements").read_bytes()
        )
        self.assertEqual(
            entitlements["com.apple.developer.associated-domains"],
            ["applinks:www.checkupauto.fr"],
        )

    def test_xctest_target_lists_real_test_sources(self):
        required = (
            "Tests/DeviceRegistrationTests.swift",
            "Tests/NotificationRoutingTests.swift",
            "Tests/MobileAPITests.swift",
            "Tests/MobileBootstrapTests.swift",
            "Tests/MobileDeadlineSyncTests.swift",
            "Tests/ReminderPlanTests.swift",
            "Tests/VehicleClaimTests.swift",
            "Tests/AuthoritativeInventoryTests.swift",
        )
        for source in required:
            self.assertIn(source, self.text)


if __name__ == "__main__":
    unittest.main()
