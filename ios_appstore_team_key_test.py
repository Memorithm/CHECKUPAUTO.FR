import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


class InstallAppStoreTeamKeyTest(unittest.TestCase):
    def test_shell_syntax(self):
        subprocess.run(
            ["bash", "-n", "scripts/install-appstore-team-key.sh"],
            check=True,
            timeout=10,
        )

    def test_rejects_bad_filename_without_touching_vault(self):
        script = Path("scripts/install-appstore-team-key.sh")
        self.assertTrue(script.is_file())
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            key = Path(tmp) / "wrong.p8"
            key.write_text("-----BEGIN " + "PRIVATE KEY-----\nabc\n-----END " + "PRIVATE KEY-----\n")
            result = subprocess.run(
                ["bash", str(script), str(key), "12345678-1234-1234-1234-123456789abc"],
                env={**os.environ, "HOME": str(home)},
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((home / "Library/Application Support/CheckupAuto").exists())

    def test_installs_private_key_and_issuer_with_strict_permissions(self):
        script = Path("scripts/install-appstore-team-key.sh")
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            key = Path(tmp) / "AuthKey_ABC1234567.p8"
            key.write_text("-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n")
            result = subprocess.run(
                ["bash", str(script), str(key), "12345678-1234-1234-1234-123456789abc"],
                env={**os.environ, "HOME": str(home)},
                check=True,
                capture_output=True,
                text=True,
            )
            root = home / "Library/Application Support/CheckupAuto/AppStoreConnect"
            installed = root / key.name
            issuer = root / "issuer-id"
            self.assertTrue(installed.is_file())
            self.assertEqual(issuer.read_text().strip(), "12345678-1234-1234-1234-123456789abc")
            self.assertEqual(stat.S_IMODE(root.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(installed.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(issuer.stat().st_mode), 0o600)
            self.assertIn("CHECKUPAUTO_APPSTORE_TEAM_KEY_INSTALLED", result.stdout)


if __name__ == "__main__":
    unittest.main()
