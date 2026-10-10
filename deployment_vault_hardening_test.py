"""S-15: vault key outside the vault, no symlink following, serialised writes."""
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import deployment_center as center
import deployment_vault as vault


class DeploymentVaultHardeningTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        env = mock.patch.dict(os.environ, {}, clear=False)
        env.start(); self.addCleanup(env.stop)
        os.environ.pop(vault.KEY_FILE_ENV, None)
        os.environ.pop("CREDENTIALS_DIRECTORY", None)
        self.target = center.validate_target({
            "provider": "planethoster-n0c", "host": "ssh.example.net", "username": "checkup",
            "domain": "www.checkupauto.fr", "authMode": "password",
        })

    def test_symlinked_key_is_refused(self):
        root = self.base / "vault"; root.mkdir()
        elsewhere = self.base / "attacker.key"; elsewhere.write_bytes(b"k" * 32)
        (root / "master.key").symlink_to(elsewhere)
        with self.assertRaises(RuntimeError):
            vault.DeploymentVault(root).store("prod", self.target, password="pw")

    def test_external_key_file_is_used_and_nothing_is_created_beside_data(self):
        key = self.base / "credentials" / "vault.key"; key.parent.mkdir(); key.write_bytes(os.urandom(32))
        os.environ[vault.KEY_FILE_ENV] = str(key)
        root = self.base / "vault"
        v = vault.DeploymentVault(root)
        v.store("prod", self.target, password="pw")
        self.assertFalse((root / "master.key").exists())
        self.assertEqual(vault.DeploymentVault(root).load("prod")["credential"]["password"], "pw")
        os.environ.pop(vault.KEY_FILE_ENV)
        # Without the external key the data cannot be decrypted.
        with self.assertRaises(RuntimeError):
            vault.DeploymentVault(root).load("prod")

    def test_missing_external_key_fails_closed(self):
        os.environ[vault.KEY_FILE_ENV] = str(self.base / "absent.key")
        with self.assertRaises(RuntimeError):
            vault.DeploymentVault(self.base / "vault").store("prod", self.target, password="pw")

    def test_systemd_credential_is_picked_up(self):
        creds = self.base / "creds"; creds.mkdir(); (creds / vault.SYSTEMD_CREDENTIAL).write_bytes(os.urandom(32))
        os.environ["CREDENTIALS_DIRECTORY"] = str(creds)
        v = vault.DeploymentVault(self.base / "vault")
        self.assertEqual(v.key_path, creds / vault.SYSTEMD_CREDENTIAL)

    def test_concurrent_stores_do_not_lose_updates(self):
        root = self.base / "vault"
        names = [f"t{i}" for i in range(16)]
        barrier = threading.Barrier(len(names))

        def worker(name):
            barrier.wait()
            vault.DeploymentVault(root).store(name, self.target, password="pw-" + name)

        threads = [threading.Thread(target=worker, args=(n,)) for n in names]
        for t in threads: t.start()
        for t in threads: t.join()
        stored = {row["name"] for row in vault.DeploymentVault(root).summaries()}
        self.assertEqual(stored, set(names))


if __name__ == "__main__":
    unittest.main()
