from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parent
DEPLOY=ROOT/"deploy/hostinger/deploy-staging.sh"

class HostingerPrivatePermissionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text=DEPLOY.read_text(encoding="utf-8")

    def test_integration_private_directory_is_bounded_and_owned_by_runtime_uid(self):
        self.assertIn('INTEGRATIONS="$STATE/private/integrations"',self.text)
        self.assertIn('install -d -o 10001 -g 10001 -m 0700 "$INTEGRATIONS"',self.text)
        self.assertIn('chown 10001:10001 "$item"',self.text)
        self.assertIn('chmod 0600 "$item"',self.text)

    def test_symlinks_and_unexpected_integration_files_fail_closed(self):
        self.assertIn('if [ -L "$INTEGRATIONS" ]; then',self.text)
        self.assertIn("STAGING_PRIVATE_INTEGRATIONS_SYMLINK_REFUSED",self.text)
        self.assertIn('if [ -L "$item" ] || [ ! -f "$item" ]; then',self.text)
        self.assertIn("STAGING_PRIVATE_INTEGRATION_FILE_INVALID",self.text)

    def test_permission_fix_does_not_recursively_chown_all_private_material(self):
        self.assertNotIn('chown -R 10001:10001 "$STATE/private"',self.text)
        self.assertNotIn('chmod -R',self.text)

if __name__=="__main__":
    unittest.main()
