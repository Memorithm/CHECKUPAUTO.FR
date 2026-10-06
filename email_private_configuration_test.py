import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import email_gateway as mail


class EmailPrivateConfigurationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = mock.patch.dict(
            os.environ,
            {"CYBERCHECK_PRIVATE_DIR": self.tmp.name},
            clear=True,
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    @staticmethod
    def payload(**overrides):
        data = {
            "host": "mail.checkupauto.fr",
            "port": 465,
            "mode": "ssl",
            "sender": "contact@checkupauto.fr",
            "username": "contact@checkupauto.fr",
            "password": "private-mailbox-secret",
        }
        data.update(overrides)
        return data

    def test_private_smtp_is_atomic_private_and_never_returned(self):
        info = mail.save_private_smtp_config(self.payload())
        path = mail._smtp_private_path()
        self.assertTrue(path.is_file())
        self.assertFalse(path.is_symlink())
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertTrue(info["configured"])
        self.assertEqual(info["source"], "private")
        self.assertTrue(info["passwordConfigured"])
        self.assertNotIn("password", info)
        self.assertNotIn("private-mailbox-secret", repr(info))

        cfg = mail.load_config()
        self.assertEqual(cfg.host, "mail.checkupauto.fr")
        self.assertEqual(cfg.port, 465)
        self.assertEqual(cfg.mode, "ssl")
        self.assertEqual(cfg.sender, "contact@checkupauto.fr")
        self.assertEqual(cfg.username, "contact@checkupauto.fr")
        self.assertEqual(cfg.password, "private-mailbox-secret")

    def test_blank_password_preserves_existing_secret_for_same_username(self):
        mail.save_private_smtp_config(self.payload())
        info = mail.save_private_smtp_config(
            self.payload(password="", sender="rappel@checkupauto.fr")
        )
        self.assertTrue(info["passwordConfigured"])
        self.assertEqual(mail.load_config().password, "private-mailbox-secret")
        self.assertEqual(mail.load_config().sender, "rappel@checkupauto.fr")

    def test_changed_username_requires_new_password(self):
        mail.save_private_smtp_config(self.payload())
        with self.assertRaises(ValueError):
            mail.save_private_smtp_config(
                self.payload(username="other@checkupauto.fr", password="")
            )

    def test_environment_configuration_overrides_private_store(self):
        mail.save_private_smtp_config(self.payload())
        with mock.patch.dict(
            os.environ,
            {
                "CYBERCHECK_SMTP_FROM": "env@checkupauto.fr",
                "CYBERCHECK_SMTP_HOST": "127.0.0.1",
                "CYBERCHECK_SMTP_PORT": "25",
                "CYBERCHECK_SMTP_MODE": "plain",
            },
            clear=False,
        ):
            cfg = mail.load_config()
            info = mail.smtp_config_info()
        self.assertEqual(cfg.sender, "env@checkupauto.fr")
        self.assertEqual(cfg.host, "127.0.0.1")
        self.assertEqual(info["source"], "environment")

    def test_incomplete_remote_private_config_is_diagnostic_not_ready(self):
        info = mail.save_private_smtp_config(
            self.payload(username="", password="")
        )
        self.assertTrue(info["configured"])
        self.assertFalse(info["usernameConfigured"])
        with mock.patch("email_gateway.smtplib.SMTP_SSL") as smtp:
            state = mail.smtp_preflight()
        self.assertFalse(state["ready"])
        self.assertEqual(state["state"], "awaiting_credentials")
        self.assertEqual(
            state["reason"],
            "authentication_required_for_remote_relay",
        )
        smtp.assert_not_called()

    def test_delete_removes_only_private_config(self):
        mail.save_private_smtp_config(self.payload())
        result = mail.delete_private_smtp_config()
        self.assertFalse(mail._smtp_private_path().exists())
        self.assertFalse(result["configured"])
        self.assertEqual(result["source"], "none")

    def test_private_config_refuses_symlink_and_control_char_secret(self):
        path = mail._smtp_private_path()
        path.parent.mkdir(parents=True)
        target = Path(self.tmp.name) / "outside.json"
        target.write_text("{}")
        path.symlink_to(target)
        with self.assertRaises(RuntimeError):
            mail.save_private_smtp_config(self.payload())
        path.unlink()
        with self.assertRaises(ValueError):
            mail.save_private_smtp_config(
                self.payload(password="bad\nsecret")
            )

    def test_private_file_schema_is_exact_and_secret_is_not_plaintext_api_state(self):
        mail.save_private_smtp_config(self.payload())
        raw = json.loads(mail._smtp_private_path().read_text())
        self.assertEqual(raw["schema"], mail.SMTP_PRIVATE_SCHEMA)
        self.assertEqual(raw["password"], "private-mailbox-secret")
        info = mail.smtp_config_info()
        self.assertNotIn("password", info)
        self.assertTrue(info["passwordConfigured"])


if __name__ == "__main__":
    unittest.main()
