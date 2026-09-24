from pathlib import Path
import unittest


WORKFLOW = Path(__file__).parent / ".github" / "workflows" / "hostinger-staging-deploy.yml"


class HostingerStagingControlPlaneTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_repository_workflow_is_a_release_gate(self):
        self.assertIn("name: Hostinger staging release gate", self.text)
        self.assertIn("HOSTINGER_RELEASE_READY_FOR_REMOTEOPS=$GITHUB_SHA", self.text)
        self.assertIn("Memorithm/RemoteOps is the privileged deployment control plane", self.text)

    def test_release_gate_uses_repository_runner(self):
        self.assertIn("runs-on: [self-hosted, Linux, ARM64, internal]", self.text)
        self.assertNotIn("runs-on: [self-hosted, Linux, ARM64, remoteops, thor]", self.text)

    def test_privileged_remote_material_is_not_used_here(self):
        for forbidden in (
            "/srv/remoteops/keys",
            "HOSTINGER_KEY:",
            "HOSTINGER_KNOWN_HOSTS:",
            "sudo -n ssh",
            '"root@$HOSTINGER_HOST"',
            "Upload immutable release",
            "Deploy and verify staging",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.text)

    def test_exact_checkout_and_clean_tree_are_required(self):
        self.assertIn('test "$(git rev-parse HEAD)" = "$GITHUB_SHA"', self.text)
        self.assertIn("git diff --quiet", self.text)
        self.assertIn("git diff --cached --quiet", self.text)
        self.assertIn("persist-credentials: false", self.text)


if __name__ == "__main__":
    unittest.main()
