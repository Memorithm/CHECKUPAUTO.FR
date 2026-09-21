import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent
CLI = ROOT / "scripts" / "checkupauto-deployctl.py"


class DeploymentCLITest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = os.environ.copy()
        self.env["CYBERCHECK_DEPLOYMENT_VAULT"] = str(self.root / "vault")

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args, input_text=None):
        return subprocess.run(
            [sys.executable, str(CLI), *args],
            cwd=ROOT,
            input=input_text,
            text=True,
            capture_output=True,
            env=self.env,
            check=False,
            timeout=10,
        )

    def target_file(self, auth_mode="password"):
        path = self.root / f"target-{auth_mode}.json"
        path.write_text(json.dumps({
            "provider": "planethoster-n0c",
            "host": "ssh.example.net",
            "username": "checkup",
            "domain": "www.checkupauto.fr",
            "authMode": auth_mode,
        }), encoding="utf-8")
        return path

    def test_profiles_command_exposes_planethoster_presets(self):
        result = self.run_cli("profiles")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["planethoster-n0c"]["defaultPort"], 5022)
        self.assertEqual(payload["planethoster-cpanel"]["defaultPort"], 2908)
        self.assertEqual(payload["planethoster-n0c"]["defaultRoot"], ".checkupauto")
        self.assertEqual(payload["planethoster-n0c"]["defaultWebRoot"], "public_html")

    def test_validate_command_separates_private_and_public_roots(self):
        result = self.run_cli(
            "validate",
            "--target",
            str(self.target_file()),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["port"], 5022)
        self.assertEqual(payload["root_path"], ".checkupauto")
        self.assertEqual(payload["web_root_path"], "public_html")

    def test_password_save_uses_stdin_and_list_is_redacted(self):
        target = self.target_file("password")
        secret = "cli-secret-value"
        saved = self.run_cli(
            "save",
            "--name",
            "production",
            "--target",
            str(target),
            "--password-stdin",
            input_text=secret + "\n",
        )
        self.assertEqual(saved.returncode, 0, saved.stderr)
        self.assertNotIn(secret, saved.stdout)
        self.assertNotIn(secret, saved.stderr)

        listed = self.run_cli("list")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertNotIn(secret, listed.stdout)
        payload = json.loads(listed.stdout)
        self.assertEqual(payload[0]["name"], "production")
        self.assertTrue(payload[0]["credentialStored"])

        encrypted = (self.root / "vault" / "targets.enc").read_bytes()
        self.assertNotIn(secret.encode(), encrypted)

    def test_invalid_target_returns_machine_readable_error(self):
        path = self.root / "invalid.json"
        path.write_text(json.dumps({
            "provider": "planethoster-n0c",
            "host": "bad host",
            "username": "user",
            "domain": "example.net",
        }), encoding="utf-8")
        result = self.run_cli("validate", "--target", str(path))
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stderr)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "ValueError")


if __name__ == "__main__":
    unittest.main()
