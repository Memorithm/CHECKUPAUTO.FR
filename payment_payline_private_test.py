import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import payment_payline_private as private


class PaylinePrivateConfigurationTest(unittest.TestCase):
    def write(self, root: Path, payload=None, mode=0o600):
        path=root/"payline-sandbox.json"
        path.write_text(json.dumps(payload or {
            "environment":"sandbox",
            "merchantId":"00000012345678",
            "accessKey":"synthetic-private-key",
            "contractNumber":"TEST_CONTRACT_01",
            "publicOrigin":"https://stage.example",
        }), encoding="utf-8")
        path.chmod(mode)
        return path

    def test_missing_configuration_is_explicit_and_never_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"missing.json"
            with patch.dict(os.environ, {"CYBERCHECK_PAYLINE_CONFIG_PATH":str(path)}, clear=False):
                status=private.status()
            self.assertFalse(status["configured"])
            self.assertFalse(status["ready"])
            self.assertTrue(status["transportImplemented"])
            self.assertFalse(status["livePaymentsEnabled"])
            self.assertEqual(status["configurationState"],"missing")

    def test_private_file_loads_without_exposing_secret_in_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=self.write(Path(tmp))
            with patch.dict(os.environ, {"CYBERCHECK_PAYLINE_CONFIG_PATH":str(path)}, clear=False):
                cfg=private.load()
                status=private.status()
            self.assertEqual(cfg.merchant_id,"00000012345678")
            self.assertTrue(status["configured"])
            self.assertTrue(status["configurationValid"])
            self.assertFalse(status["credentialsVerified"])
            self.assertTrue(status["checkoutBound"])
            self.assertNotIn("synthetic-private-key", repr(status))
            self.assertNotIn("00000012345678", repr(status))
            self.assertNotIn("TEST_CONTRACT_01", repr(status))

    def test_group_or_world_access_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=self.write(Path(tmp), mode=0o640)
            with patch.dict(os.environ, {"CYBERCHECK_PAYLINE_CONFIG_PATH":str(path)}, clear=False):
                with self.assertRaisesRegex(private.PaylinePrivateConfigurationError, "^payline_private_permissions_invalid$"):
                    private.load()
                status=private.status()
            self.assertEqual(status["configurationState"],"invalid")

    def test_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            real=self.write(root)
            link=root/"link.json"
            link.symlink_to(real)
            with patch.dict(os.environ, {"CYBERCHECK_PAYLINE_CONFIG_PATH":str(link)}, clear=False):
                with self.assertRaises(private.PaylinePrivateConfigurationError):
                    private.load()

    def test_configuration_must_live_outside_source_tree(self):
        inside=Path(__file__).resolve().parent/"synthetic-payline-private.json"
        with patch.dict(os.environ, {"CYBERCHECK_PAYLINE_CONFIG_PATH":str(inside)}, clear=False):
            with self.assertRaisesRegex(private.PaylinePrivateConfigurationError, "^payline_private_outside_source_required$"):
                private.config_path()


if __name__ == "__main__":
    unittest.main()
