"""No network, no production secrets: private Basic credential rotation contracts."""
import base64
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import stat
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import admin_password


class PasswordRotationTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "admin-password"
        self.old = "Test-only-Initial#405"
        self.path.write_text(self.old + "\n", encoding="utf-8")
        self.path.chmod(0o600)

    def change(self, new="Test-only-Next#406", old=None, confirm=None):
        admin_password.change(
            old=self.old if old is None else old,
            new=new,
            confirmation=new if confirm is None else confirm,
            path=self.path,
        )

    def test_successful_rotation_is_private_and_immediate(self):
        next_password = "Test-only-Next#406"
        self.assertTrue(admin_password.verify(self.old, path=self.path))
        self.change(new=next_password)
        self.assertFalse(admin_password.verify(self.old, path=self.path))
        self.assertTrue(admin_password.verify(next_password, path=self.path))
        self.assertEqual(self.path.read_text(), next_password + "\n")
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertFalse(list(self.path.parent.glob(".admin-password-new-*")))

    def test_old_password_mismatch_does_not_rotate(self):
        with self.assertRaisesRegex(ValueError, "admin_password_current_invalid"):
            self.change(old="not-the-password")
        self.assertTrue(admin_password.verify(self.old, path=self.path))

    def test_confirmation_and_reuse_refused(self):
        with self.assertRaisesRegex(ValueError, "confirmation_mismatch"):
            self.change(confirm="another")
        with self.assertRaisesRegex(ValueError, "password_unchanged"):
            self.change(new=self.old)
        self.assertTrue(admin_password.verify(self.old, path=self.path))

    def test_password_policy(self):
        for candidate in ("short", " leading-space", "tail-space ", "a\nnewline",
                          "x" * 129, "tab\tseparated"):
            with self.subTest(length=len(candidate)), self.assertRaisesRegex(
                ValueError, "admin_password_new_invalid"
            ):
                self.change(new=candidate)
        self.assertTrue(admin_password.verify(self.old, path=self.path))

    def test_no_symlink_or_public_password_file(self):
        linked = self.path.with_name("linked-password")
        linked.symlink_to(self.path)
        self.assertFalse(admin_password.verify(self.old, path=linked))
        with self.assertRaises(OSError):
            admin_password.change(old=self.old, new="New-safe-pass#9",
                                  confirmation="New-safe-pass#9", path=linked)
        self.path.chmod(0o644)
        self.assertFalse(admin_password.verify(self.old, path=self.path))
        self.path.chmod(0o600)

    def test_root_owned_0640_secret_is_allowed_for_its_service_group(self):
        # Exercise a simulated cybercheck process without chowning a real
        # fixture or reading a production credential.
        info = SimpleNamespace(
            st_mode=stat.S_IFREG | 0o640,
            st_uid=0,
            st_gid=2301,
            st_size=self.path.stat().st_size,
        )
        with patch.object(admin_password.os, "fstat", return_value=info), \
             patch.object(admin_password.os, "geteuid", return_value=2300), \
             patch.object(admin_password.os, "getegid", return_value=2301):
            self.assertTrue(admin_password.verify(self.old, path=self.path))
            self.assertFalse(admin_password.verify("incorrect", path=self.path))

    def test_root_owned_secret_rejects_wrong_group_or_extra_permissions(self):
        actual_size=self.path.stat().st_size
        for owner, group, mode in (
            (0, 9999, 0o640),  # different primary group
            (0, 2301, 0o660),  # group can mutate credential
            (0, 2301, 0o644),  # everyone can read
            (0, 2301, 0o440),  # only the approved 0640 layout is supported
            (2302, 2301, 0o640),  # arbitrary file owner
        ):
            with self.subTest(owner=owner, group=group, mode=oct(mode)):
                info = SimpleNamespace(st_mode=stat.S_IFREG | mode,
                                       st_uid=owner, st_gid=group,
                                       st_size=actual_size)
                with patch.object(admin_password.os, "fstat", return_value=info), \
                     patch.object(admin_password.os, "geteuid", return_value=2300), \
                     patch.object(admin_password.os, "getegid", return_value=2301):
                    self.assertFalse(admin_password.verify(self.old, path=self.path))

    def test_two_concurrent_changes_cannot_overwrite_one_another(self):
        def attempt(password):
            try:
                self.change(new=password)
                return True
            except ValueError:
                return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, ["Concurrent-choice-A!","Concurrent-choice-B!"]))
        self.assertEqual(results.count(True), 1)
        self.assertFalse(admin_password.verify(self.old, path=self.path))

    def test_csrf_is_bound_to_basic_cookie_and_password_rotation(self):
        class Headers(dict):
            pass
        base = Headers({"Authorization":"Basic TEST-CREDS","Cookie":"test-cookie"})
        first = admin_password.csrf_token(base, path=self.path, hour=999999)
        self.assertEqual(len(first), 64)
        self.assertNotEqual(first, admin_password.csrf_token(
            Headers({"Authorization":"Basic DIFFERENT","Cookie":"test-cookie"}),
            path=self.path, hour=999999))
        now = admin_password.csrf_token(base, path=self.path)
        self.assertTrue(admin_password.verify_csrf(now, base, path=self.path))
        self.assertFalse(admin_password.verify_csrf(
            now, Headers({"Authorization":"Basic DIFFERENT","Cookie":"test-cookie"}),
            path=self.path))
        self.change()
        self.assertFalse(admin_password.verify_csrf(now, base, path=self.path))


if __name__ == "__main__":
    unittest.main()
