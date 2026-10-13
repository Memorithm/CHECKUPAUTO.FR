"""Offline regression tests for persistent runner-to-Mac SSH identity."""
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent
BOOTSTRAP = ROOT / "scripts" / "ensure-mac-ssh-identity.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "ios-testflight.yml"


@unittest.skipUnless(shutil.which("ssh-keygen"), "ssh-keygen is required")
class TestFlightRunnerSSHBootstrapTest(unittest.TestCase):
    def run_bootstrap(self, directory, *, summary=None):
        env = os.environ.copy()
        env.pop("GITHUB_STEP_SUMMARY", None)
        if summary is not None:
            env["GITHUB_STEP_SUMMARY"] = str(summary)
        return subprocess.run(
            ["bash", str(BOOTSTRAP), str(directory)],
            env=env, text=True, capture_output=True, timeout=20, check=False,
        )

    def test_creates_restricted_key_and_public_material_only(self):
        with tempfile.TemporaryDirectory() as temp:
            key_dir = Path(temp) / ".ssh"
            summary = Path(temp) / "summary.txt"
            result = self.run_bootstrap(key_dir, summary=summary)
            self.assertEqual(result.returncode, 0, result.stderr)
            key = key_dir / "checkupauto_macmini_ed25519"
            public = key.with_suffix(".pub") if False else Path(str(key) + ".pub")
            self.assertTrue(key.is_file())
            self.assertTrue(public.is_file())
            self.assertEqual(stat.S_IMODE(key_dir.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(key.stat().st_mode), 0o600)
            self.assertTrue(public.read_text().startswith("ssh-ed25519 "))
            self.assertIn("MAC_MINI_SSH_PUBLIC_KEY=ssh-ed25519 ", result.stdout)
            self.assertIn("MAC_MINI_SSH_PUBLIC_FINGERPRINT=SHA256:", result.stdout)
            self.assertNotIn("BEGIN OPENSSH PRIVATE KEY", result.stdout)
            self.assertNotIn("BEGIN OPENSSH PRIVATE KEY", summary.read_text())
            self.assertIn(public.read_text().strip(), summary.read_text())

    def test_idempotent_never_rotates_existing_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            key_dir = Path(temp) / ".ssh"
            first = self.run_bootstrap(key_dir)
            self.assertEqual(first.returncode, 0, first.stderr)
            key = key_dir / "checkupauto_macmini_ed25519"
            original = key.read_bytes()
            second = self.run_bootstrap(key_dir)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(key.read_bytes(), original)
            fingerprint = re.search(r"MAC_MINI_SSH_PUBLIC_FINGERPRINT=(.+)", first.stdout)
            self.assertIsNotNone(fingerprint)
            self.assertIn(fingerprint.group(1), second.stdout)

    def test_symlink_directory_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            dest = Path(temp) / "sensitive"
            dest.mkdir()
            alias = Path(temp) / "ssh-link"
            alias.symlink_to(dest, target_is_directory=True)
            result = self.run_bootstrap(alias)
            self.assertEqual(result.returncode, 2)
            self.assertFalse(list(dest.iterdir()))

    def test_orphan_public_key_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            key_dir = Path(temp) / ".ssh"
            key_dir.mkdir()
            public = key_dir / "checkupauto_macmini_ed25519.pub"
            public.write_text("ssh-ed25519 orphan\n")
            result = self.run_bootstrap(key_dir)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(public.read_text(), "ssh-ed25519 orphan\n")

    def test_release_only_targets_qualified_runner(self):
        workflow = WORKFLOW.read_text()
        self.assertIn("runs-on: [self-hosted, Linux, ARM64, internal, checkupauto-ci]", workflow)
        self.assertIn('"${RUNNER_NAME:-}" != "checkupauto-thor-arm64-02"', workflow)
        self.assertIn('"$(id -un)" != "memci-checkupauto"', workflow)
        self.assertIn('bash scripts/ensure-mac-ssh-identity.sh "$HOME/.ssh"', workflow)
        self.assertLess(workflow.index("Provision isolated runner SSH identity"),
                        workflow.index("Resolve authorized Mac SSH identity"))
        self.assertIn("CHECKUPAUTO_MAC_SSH_KEY: ${{ secrets.CHECKUPAUTO_MAC_SSH_KEY }}", workflow)
        self.assertIn("-o BatchMode=yes", workflow)
        self.assertIn("-o IdentitiesOnly=yes", workflow)
        self.assertIn("StrictHostKeyChecking=accept-new", workflow)


if __name__ == "__main__":
    unittest.main()
