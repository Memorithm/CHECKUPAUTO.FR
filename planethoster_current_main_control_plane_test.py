from pathlib import Path
import unittest


ROOT=Path(__file__).resolve().parent
WORKFLOW=ROOT/".github/workflows/planethoster-test-current-main.yml"


class PlanetHosterCurrentMainControlPlaneTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text=WORKFLOW.read_text(encoding="utf-8")

    def test_privileged_deploy_is_pinned_to_remoteops_mac_mini(self):
        self.assertIn(
            "runs-on: [self-hosted, macOS, ARM64, remoteops, mac-mini]",
            self.text,
        )
        self.assertNotIn("runs-on: [self-hosted, Linux, ARM64, internal]",self.text)
        self.assertIn('test "$(hostname)" = "Mac-mini-de-tarek.local"',self.text)

    def test_existing_remoteops_planethoster_identity_is_required(self):
        self.assertIn(
            'key="$HOME/.ssh/checkupauto_planethoster_test_ed25519"',
            self.text,
        )
        self.assertIn(
            'hosts="$HOME/.ssh/checkupauto_planethoster_test_known_hosts"',
            self.text,
        )
        self.assertIn("STAGING_KEY=%s",self.text)
        self.assertIn("STAGING_KNOWN_HOSTS=%s",self.text)
        self.assertIn(
            "SHA256:bSsRNwbVPWB1mHLo7qwavQPg9TUQOF+I40idG8ezcUs",
            self.text,
        )
        self.assertIn('ssh-keygen -y -f "$key"',self.text)
        self.assertNotIn("ssh-keygen -t",self.text)
        self.assertNotIn("ssh-keyscan",self.text)
        self.assertNotIn("runner.home",self.text)

    def test_release_is_still_exact_green_current_main(self):
        self.assertIn('workflows: ["Security CI"]',self.text)
        self.assertIn("github.event.workflow_run.conclusion == 'success'",self.text)
        self.assertIn("github.event.workflow_run.event == 'push'",self.text)
        self.assertIn('test "$(git rev-parse HEAD)" = "$RELEASE_SHA"',self.text)
        self.assertIn(
            "Security CI SHA is no longer current main; stale deployment refused",
            self.text,
        )
        self.assertIn(
            "scripts/checkupauto-planethoster-legacy-staging-deploy.py",
            self.text,
        )


if __name__=="__main__":
    unittest.main()
