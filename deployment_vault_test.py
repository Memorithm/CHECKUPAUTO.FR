import os
import tempfile
import unittest
from pathlib import Path

import deployment_center as center
import deployment_vault as vault


class DeploymentVaultTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "vault"
        self.vault = vault.DeploymentVault(self.root)
        self.key_target = center.validate_target({
            "provider": "planethoster-n0c",
            "host": "ssh.example.net",
            "username": "checkup",
            "domain": "www.checkupauto.fr",
            "authMode": "key",
        })
        self.password_target = center.validate_target({
            "provider": "planethoster-n0c",
            "host": "ssh.example.net",
            "username": "checkup",
            "domain": "www.checkupauto.fr",
            "authMode": "password",
        })

    def tearDown(self):
        self.tmp.cleanup()

    def test_password_is_encrypted_at_rest(self):
        secret = "very-secret-password"
        self.vault.store("production", self.password_target, password=secret)
        raw = self.vault.data_path.read_bytes()
        self.assertNotIn(secret.encode(), raw)
        self.assertEqual(self.vault.load("production")["credential"]["password"], secret)

    def test_key_path_is_stored_inside_encrypted_payload(self):
        key_path = "/home/user/.ssh/checkupauto"
        self.vault.store("production", self.key_target, identity_file=key_path)
        raw = self.vault.data_path.read_bytes()
        self.assertNotIn(key_path.encode(), raw)
        self.assertEqual(
            self.vault.load("production")["credential"]["identityFile"],
            key_path,
        )

    def test_vault_permissions_are_private(self):
        self.vault.store("production", self.password_target, password="secret")
        self.assertEqual(self.root.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.vault.key_path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.vault.data_path.stat().st_mode & 0o777, 0o600)

    def test_summaries_never_expose_credentials(self):
        self.vault.store("production", self.password_target, password="secret")
        rows = self.vault.summaries()
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["credentialStored"])
        self.assertEqual(rows[0]["authMode"], "password")
        self.assertNotIn("credential", rows[0])
        self.assertNotIn("passwordValue", rows[0])
        self.assertNotIn("secret", str(rows[0]))

    def test_generated_admin_password_is_stable_and_encrypted(self):
        self.vault.store("production", self.password_target, password="ssh-secret")
        first = self.vault.ensure_admin_password("production")
        second = self.vault.ensure_admin_password("production")
        self.assertEqual(first, second)
        self.assertGreaterEqual(len(first), 32)
        self.assertEqual(self.vault.admin_password("production"), first)
        raw = self.vault.data_path.read_bytes()
        self.assertNotIn(first.encode(), raw)
        self.assertNotIn(b"adminPassword", raw)

    def test_admin_password_requires_existing_target(self):
        with self.assertRaises(KeyError):
            self.vault.ensure_admin_password("missing")

    def test_delete_removes_target(self):
        self.vault.store("production", self.password_target, password="secret")
        self.assertTrue(self.vault.delete("production"))
        self.assertFalse(self.vault.delete("production"))
        with self.assertRaises(KeyError):
            self.vault.load("production")

    def test_invalid_target_name_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "nom de cible"):
            self.vault.store("../prod", self.password_target, password="secret")

    def test_wrong_master_key_fails_closed(self):
        self.vault.store("production", self.password_target, password="secret")
        self.vault.key_path.write_bytes(os.urandom(32))
        with self.assertRaisesRegex(RuntimeError, "illisible"):
            self.vault.load("production")

    def test_missing_auth_material_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "clé SSH"):
            self.vault.store("key", self.key_target)
        with self.assertRaisesRegex(ValueError, "mot de passe"):
            self.vault.store("password", self.password_target, password="")


if __name__ == "__main__":
    unittest.main()
