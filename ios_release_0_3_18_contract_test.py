"""Version and release notes contract for TestFlight 0.3.18 (21)."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IOS = ROOT / "ios/CheckupAutoReminder"


class IOSRelease018Contract(unittest.TestCase):
    def test_exact_release_identity(self):
        import re
        spec = (IOS / "project.yml").read_text(encoding="utf-8")
        build = re.search(r"CURRENT_PROJECT_VERSION: (\d+)", spec)
        version = re.search(r"MARKETING_VERSION: (\d+)\.(\d+)\.(\d+)", spec)
        self.assertIsNotNone(build)
        self.assertIsNotNone(version)
        self.assertGreaterEqual(int(build.group(1)), 21)
        self.assertGreaterEqual(tuple(map(int, version.groups())), (0, 3, 18))
        self.assertIn("CHECKUPAUTO_ENVIRONMENT: production", spec)

    def test_release_notes_cover_performance_and_security(self):
        notes = (IOS / "RELEASE_NOTES_0.3.18.md").read_text(encoding="utf-8")
        for item in ("0.3.18 (21)", "WebKit", "HttpOnly", "Secure",
                     "14/10/2027", "RemoteOps", "TestFlight"):
            self.assertIn(item, notes)


if __name__ == "__main__":
    unittest.main()
