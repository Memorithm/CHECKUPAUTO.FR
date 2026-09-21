import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import email_settings


class EmailSettingsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "email"
        self.store = email_settings.EmailSettingsStore(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def remote_payload(password="super-secret"):
        return {
            "transportMode": "smtp",
            "smtp": {
                "host": "smtp.example.fr",
                "port": 587,
                "sender": "contact@checkupauto.fr",
                "mode": "starttls",
                "username": "mailer-user",
                "password": password,
            },
        }

    def test_remote_smtp_secret_is_encrypted_and_summary_is_redacted(self):
        summary = self.store.save(self.remote_payload())
        self.assertTrue(summary["configured"])
        self.assertTrue(summary["smtp"]["passwordStored"])
        self.assertNotIn("super-secret", str(summary))
        raw = self.store.data_path.read_bytes()
        self.assertNotIn(b"super-secret", raw)
        loaded = self.store.load()
        self.assertEqual(loaded["smtp"]["password"], "super-secret")

    def test_blank_password_preserves_existing_secret_for_same_username(self):
        self.store.save(self.remote_payload("first-secret"))
        payload = self.remote_payload("")
        payload["smtp"]["sender"] = "rappel@checkupauto.fr"
        summary = self.store.save(payload)
        self.assertTrue(summary["smtp"]["passwordStored"])
        self.assertEqual(
            self.store.load()["smtp"]["password"],
            "first-secret",
        )
        self.assertEqual(
            self.store.load()["smtp"]["sender"],
            "rappel@checkupauto.fr",
        )

    def test_remote_relay_without_authentication_is_rejected(self):
        payload = self.remote_payload("")
        payload["smtp"]["username"] = ""
        with self.assertRaisesRegex(ValueError, "authentification requise"):
            self.store.save(payload)

    def test_local_plain_relay_can_be_stored_without_credentials(self):
        summary = self.store.save({
            "transportMode": "smtp",
            "smtp": {
                "host": "127.0.0.1",
                "port": 25,
                "sender": "rappel@checkupauto.fr",
                "mode": "plain",
            },
        })
        self.assertTrue(summary["smtp"]["configured"])
        self.assertFalse(summary["smtp"]["passwordStored"])

    def test_authenticated_plain_smtp_is_rejected(self):
        payload = self.remote_payload()
        payload["smtp"]["mode"] = "plain"
        payload["smtp"]["port"] = 25
        with self.assertRaisesRegex(ValueError, "exige TLS"):
            self.store.save(payload)

    def test_gmail_mode_can_disable_stored_smtp(self):
        self.store.save(self.remote_payload())
        summary = self.store.save({
            "transportMode": "gmail",
            "smtp": {},
        })
        self.assertEqual(summary["transportMode"], "gmail")
        self.assertFalse(summary["smtp"]["configured"])
        self.assertEqual(self.store.load()["smtp"], {})

    def test_permissions_are_private(self):
        self.store.save(self.remote_payload())
        self.assertEqual(self.root.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.store.key_path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.store.data_path.stat().st_mode & 0o777, 0o600)

    def test_delete_removes_encrypted_configuration(self):
        self.store.save(self.remote_payload())
        self.assertTrue(self.store.delete())
        self.assertEqual(self.store.load(), {})
        self.assertFalse(self.store.delete())

    def test_state_dir_uses_dedicated_private_subdirectory(self):
        with mock.patch.dict(
            os.environ,
            {"CYBERCHECK_PRIVATE_DIR": "/private/checkup"},
            clear=True,
        ):
            self.assertEqual(
                email_settings.state_dir(),
                Path("/private/checkup/email"),
            )


if __name__ == "__main__":
    unittest.main()
