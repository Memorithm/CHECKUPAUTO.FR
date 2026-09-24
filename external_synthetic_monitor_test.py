import unittest
from pathlib import Path

WORKFLOW = Path(".github/workflows/external-synthetic-monitor.yml")


class ExternalSyntheticMonitorWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_ephemeral_payload_files_are_required(self):
        self.assertGreaterEqual(self.text.count('body="$(mktemp)"'), 5)
        for legacy_path in (
            "/tmp/mobile-bootstrap.json",
            "/tmp/booking-services.json",
            "/tmp/site-config.json",
            "/tmp/legacy-public.html",
        ):
            self.assertNotIn(legacy_path, self.text)

    def test_expected_surfaces_remain_monitored(self):
        for expected in (
            "/api/mobile/bootstrap",
            "/api/booking/services",
            "/api/site-config",
            "https://www.checkupauto.fr",
            "noindex",
        ):
            self.assertIn(expected, self.text)

    def test_internal_runner_and_periodic_monitoring_are_locked(self):
        self.assertIn("runs-on: [self-hosted, Linux, ARM64, internal]", self.text)
        self.assertIn("cron: '*/5 * * * *'", self.text)
        self.assertIn("cancel-in-progress: true", self.text)


if __name__ == "__main__":
    unittest.main()
