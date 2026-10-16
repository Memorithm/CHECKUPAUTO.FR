"""Contract: a completed, green iOS build is delivered to TestFlight, not silently skipped.

Offline regression: no Apple credentials, GitHub Actions, SSH or Xcode required.
"""
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parent
WORKFLOW = (ROOT / ".github/workflows/ios-testflight.yml").read_text(encoding="utf-8")
CORE = (ROOT / ".github/workflows/ios-core-ci.yml").read_text(encoding="utf-8")


class TestFlightDeliveryContract(unittest.TestCase):
    def test_auto_trigger_requires_green_core_ci_on_exact_main_sha(self):
        self.assertIn("workflow_run:", WORKFLOW)
        self.assertIn("workflows: ['iOS Core CI']", WORKFLOW)
        self.assertIn("types: [completed]", WORKFLOW)
        self.assertIn("github.event.workflow_run.conclusion == 'success'", WORKFLOW)
        self.assertIn("github.event.workflow_run.event == 'push'", WORKFLOW)
        self.assertIn("github.event.workflow_run.head_branch == 'main'", WORKFLOW)
        self.assertIn("github.event.workflow_run.head_repository.full_name == github.repository", WORKFLOW)
        self.assertIn("github.event.workflow_run.head_sha == github.sha", WORKFLOW)
        self.assertIn("ref: ${{ github.event.workflow_run.head_sha || github.sha }}", WORKFLOW)
        self.assertIn('test "$(git rev-parse HEAD)" = "$expected"', WORKFLOW)
        self.assertIn("jobs:", CORE)
        self.assertIn("  swift:", CORE)
        self.assertIn("  xcode:", CORE)
        self.assertIn("needs: swift", CORE)

    def test_no_green_after_missing_apple_credentials(self):
        self.assertIn("if: ${{ steps.apple.outputs.ready != 'true' }}", WORKFLOW)
        self.assertIn("TESTFLIGHT_BLOCKED_EXTERNAL=app-store-connect-team-key", WORKFLOW)
        self.assertIn("exit 1", WORKFLOW.split("Fail closed if Apple upload credentials are missing", 1)[1].split("      - name:", 1)[0])
        self.assertIn("Build, sign and upload to TestFlight", WORKFLOW)
        self.assertIn("steps.apple.outputs.ready == 'true'", WORKFLOW)
        self.assertIn("python3 ios_release_runner.py testflight --allow-upload", WORKFLOW)
        self.assertIn("CHECKUPAUTO_MAC_SSH_KEY", WORKFLOW)

    def test_real_source_version_build_is_preserved(self):
        self.assertIn("CHECKUPAUTO_RELEASE_BUILD", WORKFLOW)
        self.assertIn('build_number="$CHECKUPAUTO_RELEASE_BUILD"', WORKFLOW)
        self.assertNotIn('build_number="$(date -u', WORKFLOW)
        self.assertIn("CURRENT_PROJECT_VERSION:", WORKFLOW)
        self.assertIn("MARKETING_VERSION:", WORKFLOW)
        self.assertIn('export CHECKUPAUTO_RELEASE_PINNED_SHA=', WORKFLOW)
        self.assertIn('export CHECKUPAUTO_BUILD_NUMBER=', WORKFLOW)

    def test_automatic_ci_upload_has_exactly_one_authoritative_publisher(self):
        # The green CHECKUPAUTO iOS CI run hands off to the RemoteOps macOS
        # publisher, which owns the authorized Apple App Store Connect secrets.
        self.assertIn("  handoff:", WORKFLOW)
        self.assertIn("TESTFLIGHT_HANDOFF=remoteops_scheduled_release", WORKFLOW)
        self.assertIn("checkupauto-testflight-auto.yml", WORKFLOW)
        self.assertIn("This job verifies the handoff condition ONLY", WORKFLOW)
        # Direct Mac-local signing remains owner-only manual recovery and must
        # never attempt a duplicate publish on a workflow_run event.
        manual = WORKFLOW.split("  testflight:", 1)[1].split("    runs-on:", 1)[0]
        self.assertIn("github.event_name == 'workflow_dispatch'", manual)
        self.assertNotIn("github.event_name == 'workflow_run'", manual)
        self.assertIn("github.actor == 'CHECKUPAUTO'", manual)

    def test_no_untrusted_pr_upload_and_no_push_race(self):
        # This workflow should only run after full iOS CI, never on a PR
        # or immediately on the still-untested main push.
        events = WORKFLOW.split("permissions:", 1)[0]
        self.assertNotIn("  pull_request:", events)
        self.assertNotIn("  push:", events)
        self.assertIn("workflow_dispatch:", events)
        self.assertIn("github.actor == 'CHECKUPAUTO'", WORKFLOW)


if __name__ == "__main__":
    unittest.main()
