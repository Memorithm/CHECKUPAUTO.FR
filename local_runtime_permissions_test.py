import grp
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest

import local_runtime_permissions as runtime_permissions


class LocalRuntimePermissionsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        subprocess.run(['git', '-C', str(self.root), 'config', 'user.email', 'ci@example.invalid'], check=True)
        subprocess.run(['git', '-C', str(self.root), 'config', 'user.name', 'CI'], check=True)
        (self.root / 'admin_server.py').write_text('print("ok")\n', encoding='utf-8')
        scripts = self.root / 'scripts'
        scripts.mkdir()
        runner = scripts / 'run.sh'
        runner.write_text('#!/bin/sh\nexit 0\n', encoding='utf-8')
        runner.chmod(0o755)
        link = self.root / 'entrypoint-link'
        link.symlink_to('admin_server.py')
        subprocess.run(['git', '-C', str(self.root), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(self.root), 'commit', '-qm', 'fixture'], check=True)
        self.group = grp.getgrgid(os.getgid()).gr_name

    def tearDown(self):
        self.temp.cleanup()

    def test_normalize_repairs_tracked_code_after_restrictive_umask_checkout(self):
        (self.root / 'admin_server.py').chmod(0o600)
        (self.root / 'scripts').chmod(0o700)
        (self.root / 'scripts' / 'run.sh').chmod(0o700)

        before = runtime_permissions.verify_checkout_permissions(self.root, self.group)
        self.assertFalse(before['ok'])

        result = runtime_permissions.normalize_checkout_permissions(self.root, self.group)

        self.assertTrue(result['ok'])
        self.assertEqual(result['trackedFiles'], 2)
        self.assertEqual(result['trackedSymlinks'], 1)
        self.assertTrue(stat.S_IMODE((self.root / 'admin_server.py').stat().st_mode) & stat.S_IRGRP)
        self.assertTrue(stat.S_IMODE((self.root / 'scripts').stat().st_mode) & stat.S_IXGRP)
        runner_mode = stat.S_IMODE((self.root / 'scripts' / 'run.sh').stat().st_mode)
        self.assertTrue(runner_mode & stat.S_IRGRP)
        self.assertTrue(runner_mode & stat.S_IXGRP)
        self.assertTrue(runtime_permissions.verify_checkout_permissions(self.root, self.group)['ok'])

    def test_normalize_does_not_touch_untracked_private_file(self):
        private = self.root / 'runtime.env'
        private.write_text('SECRET=not-a-real-secret\n', encoding='utf-8')
        private.chmod(0o600)
        initial_mode = stat.S_IMODE(private.stat().st_mode)
        initial_gid = private.stat().st_gid

        runtime_permissions.normalize_checkout_permissions(self.root, self.group)

        self.assertEqual(stat.S_IMODE(private.stat().st_mode), initial_mode)
        self.assertEqual(private.stat().st_gid, initial_gid)

    def test_verify_reports_missing_group_read_without_mutation(self):
        target = self.root / 'admin_server.py'
        target.chmod(0o600)

        result = runtime_permissions.verify_checkout_permissions(self.root, self.group)

        self.assertFalse(result['ok'])
        self.assertIn('admin_server.py', result['failures'])
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)

    def test_rejects_subdirectory_instead_of_git_root(self):
        with self.assertRaises(ValueError):
            runtime_permissions.normalize_checkout_permissions(self.root / 'scripts', self.group)


if __name__ == '__main__':
    unittest.main()
