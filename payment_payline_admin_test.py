import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import payment_payline_admin as admin
import payment_payline_private as private


class PaylineSandboxAdminTest(unittest.TestCase):
    def values(self):
        return {
            "merchantId": "00000012345678",
            "accessKey": "synthetic-private-key",
            "contractNumber": "TEST_CONTRACT_01",
        }

    def test_save_writes_private_file_and_never_returns_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "private" / "payments" / "payline-sandbox.json"
            with patch.dict(os.environ, {"CYBERCHECK_PAYLINE_CONFIG_PATH": str(path)}, clear=False):
                result = admin.save(self.values(), "https://stage.example")
                cfg = private.load()
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(cfg.merchant_id, "00000012345678")
            self.assertEqual(cfg.contract_number, "TEST_CONTRACT_01")
            self.assertEqual(cfg.public_origin, "https://stage.example")
            self.assertTrue(result["configured"])
            self.assertFalse(result["livePaymentsEnabled"])
            self.assertNotIn("synthetic-private-key", repr(result))
            self.assertNotIn("00000012345678", repr(result))
            self.assertNotIn("TEST_CONTRACT_01", repr(result))

    def test_invalid_payload_is_rejected_before_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "private" / "payline-sandbox.json"
            with patch.dict(os.environ, {"CYBERCHECK_PAYLINE_CONFIG_PATH": str(path)}, clear=False):
                with self.assertRaisesRegex(admin.PaylineSandboxAdminError, "^payline_sandbox_admin_payload_invalid$"):
                    admin.save({"accessKey": "secret"}, "https://stage.example")
            self.assertFalse(path.exists())

    def test_invalid_origin_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "payline-sandbox.json"
            with patch.dict(os.environ, {"CYBERCHECK_PAYLINE_CONFIG_PATH": str(path)}, clear=False):
                with self.assertRaisesRegex(admin.PaylineSandboxAdminError, "^payline_sandbox_admin_configuration_invalid$"):
                    admin.save(self.values(), "http://stage.example")
            self.assertFalse(path.exists())

    def test_symlink_target_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "real.json"
            target.write_text("{}")
            link = root / "payline-sandbox.json"
            link.symlink_to(target)
            with patch.dict(os.environ, {"CYBERCHECK_PAYLINE_CONFIG_PATH": str(link)}, clear=False):
                with self.assertRaisesRegex(admin.PaylineSandboxAdminError, "^payline_sandbox_admin_target_invalid$"):
                    admin.save(self.values(), "https://stage.example")


if __name__ == "__main__":
    unittest.main()
