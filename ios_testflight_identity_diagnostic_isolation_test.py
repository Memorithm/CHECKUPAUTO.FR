"""Keep privileged SSH fingerprint inspection off pull-request workflows."""
from pathlib import Path
import unittest


WORKFLOW = Path(__file__).resolve().parent / ".github" / "workflows" / "ios-testflight-key-diagnostic.yml"


class TestFlightIdentityDiagnosticIsolationTest(unittest.TestCase):
    def test_diagnostic_is_manual_only_and_main_scoped(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("on:\n  workflow_dispatch:\n", source)
        self.assertNotIn("  pull_request:", source)
        self.assertIn("github.event_name == 'workflow_dispatch'", source)
        self.assertIn("github.ref == 'refs/heads/main'", source)
        self.assertIn("github.repository == 'Memorithm/CHECKUPAUTO.FR'", source)
        self.assertIn("github.actor == 'CHECKUPAUTO'", source)
        self.assertIn("runs-on: [self-hosted, Linux, ARM64, internal, checkupauto-ci]", source)

    def test_diagnostic_never_prints_secret_material(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("ssh-keygen -y -P '' -f", source)
        self.assertIn("MAC_AUTHORIZED_KEY_MATCH", source)
        self.assertNotIn("cat \"$candidate\"", source)
        self.assertNotIn("env |", source)


if __name__ == "__main__":
    unittest.main()
