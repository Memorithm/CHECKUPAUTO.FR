import unittest
from pathlib import Path

WORKFLOW = Path(".github/workflows/external-synthetic-monitor.yml")

class ExternalSyntheticMonitorWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_ephemeral_temp_files_are_used(self):
        self.assertGreaterEqual(self.text.count('body="$(mktemp)"'), 5)

    def test_contract_surfaces_are_monitored(self):
        for expected in (
            "/api/mobile/bootstrap",
            "/api/booking/services",
            "/api/site-config",
            "https://www.checkupauto.fr",
            "noindex",
        ):
            self.assertIn(expected, self.text)

    def test_monitor_uses_internal_runner_and_schedule(self):
        self.assertIn("runs-on: [self-hosted, Linux, ARM64, internal]", self.text)
        self.assertIn("cron: '*/5 * * * *'", self.text)
        self.assertIn("cancel-in-progress: true", self.text)

if __name__ == "__main__":
    unittest.main()
