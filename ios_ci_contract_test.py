from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent
WORKFLOW = ROOT / ".github" / "workflows" / "ios-core-ci.yml"


class IOSCIContractTest(unittest.TestCase):
    def test_mac_ssh_identity_can_come_from_actions_secret_without_entering_git(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("CHECKUPAUTO_MAC_SSH_KEY: ${{ secrets.CHECKUPAUTO_MAC_SSH_KEY }}", text)
        self.assertIn("$RUNNER_TEMP/checkupauto-mac-key", text)
        self.assertIn('printf \'%s\\n\' "$CHECKUPAUTO_MAC_SSH_KEY" > "$tmp_key"', text)
        self.assertIn('if verify_key "$tmp_key"; then', text)
        self.assertNotIn("BEGIN OPENSSH PRIVATE KEY", text)
        self.assertNotIn("BEGIN RSA PRIVATE KEY", text)

    def test_unauthorized_secret_falls_back_to_runner_provisioned_identity(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("trying runner-provisioned identities", text)
        self.assertIn("remoteops_thor_ed25519", text)
        self.assertIn('if verify_key "$candidate"; then', text)
        self.assertIn('cp "$resolved" "$tmp_key"', text)
        self.assertIn("/opt/actions-runner/.ssh", text)

    def test_mac_network_preflight_precedes_ssh_identity_resolution(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        network = text.index("- name: Verify Mac SSH endpoint")
        identity = text.index("- name: Resolve authorized Mac SSH identity")
        self.assertLess(network, identity)
        self.assertIn('getent hosts "$CHECKUPAUTO_MAC_HOST"', text)
        self.assertIn('timeout 5 bash -c "</dev/tcp/$CHECKUPAUTO_MAC_HOST/22"', text)

    def test_ephemeral_identity_is_removed_even_after_failure(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("- name: Clean remote staging directory and ephemeral identity", text)
        self.assertIn("if: always()", text)
        self.assertIn('rm -f "$key"', text)
        self.assertIn("rm -f .ios-mac-key .ios-remote-dir .ios-mac-auth", text)

    def test_remote_apple_toolchain_includes_homebrew_path_and_fails_fast(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn('export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"', text)
        self.assertIn("'set -euo pipefail; export PATH=", text)

    def test_xcode_ci_reuses_release_runner_simulator_discovery(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("tar -czf - ios/CheckupAutoReminder ios_release_runner.py", text)
        self.assertIn("r.discover_simulator(require_dynamic_island=True)", text)
        self.assertIn("platform=iOS Simulator,id=", text)
        self.assertNotIn("platform=iOS Simulator,name=iPhone", text)
        self.assertIn("OWNED_CI_SIMULATOR=", text)
        self.assertIn("SIMULATOR_OWNERSHIP_MISMATCH", text)
        self.assertIn("['xcrun', 'simctl', 'delete', udid]", text)


if __name__ == "__main__":
    unittest.main()
