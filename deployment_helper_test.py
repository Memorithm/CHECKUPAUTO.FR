import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HELPER = ROOT / "deploy" / "cybercheck-deploy"
INSTALLER = ROOT / "deploy" / "install-deploy-helper.sh"


class DeploymentHelperContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.helper = HELPER.read_text(encoding="utf-8")
        cls.installer = INSTALLER.read_text(encoding="utf-8")

    def test_shell_scripts_parse(self):
        for script in (HELPER, INSTALLER):
            result = subprocess.run(
                ["bash", "-n", str(script)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_helper_is_root_only_and_accepts_one_full_sha(self):
        self.assertIn('[[ "${EUID}" -eq 0 ]]', self.helper)
        self.assertIn('[[ "$#" -eq 1 ]]', self.helper)
        self.assertRegex(
            self.helper,
            re.compile(r'\[\[ "\$EXPECTED" =~ \^\[0-9a-f\]\{40\}\$ \]\]'),
        )

    def test_helper_pins_repository_and_current_main(self):
        self.assertIn('Memorithm/CHECKUPAUTO.FR', self.helper)
        self.assertIn('[[ "$(git branch --show-current)" == "main" ]]', self.helper)
        self.assertIn('git status --porcelain=v1', self.helper)
        self.assertIn('git fetch --quiet --no-tags origin main', self.helper)
        self.assertIn('[[ "$REMOTE_HEAD" == "$EXPECTED" ]]', self.helper)

    def test_deployment_can_only_fast_forward(self):
        self.assertIn('git merge-base --is-ancestor "$CURRENT" "$EXPECTED"', self.helper)
        self.assertIn('git merge --ff-only "$EXPECTED"', self.helper)
        self.assertNotIn('git reset --hard', self.helper)
        self.assertNotIn('git checkout -f', self.helper)
        self.assertNotIn('git push --force', self.helper)

    def test_verified_sqlite_backup_happens_before_git_mutation(self):
        backup = self.helper.index('source.backup(target)')
        quick_check = self.helper.index('PRAGMA quick_check')
        merge = self.helper.index('git merge --ff-only "$EXPECTED"')
        self.assertLess(backup, merge)
        self.assertLess(quick_check, merge)
        self.assertIn('SQLite format 3\\x00', self.helper)
        self.assertIn('if not manifest:', self.helper)
        self.assertIn('"sha256": digest.hexdigest()', self.helper)
        self.assertIn('handle.read(16)', self.helper)

    def test_deployment_rebaselines_and_checks_service_health(self):
        self.assertIn('rebaseline-integrity.sh', self.helper)
        self.assertIn('systemctl restart "$SERVICE"', self.helper)
        self.assertIn('systemctl is-active --quiet "$SERVICE"', self.helper)
        self.assertIn('http://127.0.0.1:8765/', self.helper)
        self.assertIn('flock -n 9', self.helper)

    def test_installer_creates_root_owned_helper_and_narrow_sudoers_rule(self):
        self.assertIn('install -o root -g root -m 0755 "$HELPER_SOURCE" "$HELPER_TARGET"', self.installer)
        self.assertIn('install -o root -g root -m 0440 "$TMP" "$SUDOERS_TARGET"', self.installer)
        self.assertIn('%${GROUP} ALL=(root) NOPASSWD: ${HELPER_TARGET} *', self.installer)
        self.assertIn('visudo -cf "$TMP"', self.installer)
        self.assertNotIn('ALL=(ALL)', self.installer)
        self.assertNotIn('SETENV', self.installer)


if __name__ == "__main__":
    unittest.main()
