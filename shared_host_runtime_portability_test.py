import os
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parent


class SharedHostRuntimePortabilityTest(unittest.TestCase):
    def test_runtime_paths_follow_shared_host_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            security = root / "security"
            integrity = root / "integrity"
            private = root / "private"
            data = root / "data"
            gsc = private / "gsc-service-account.json"
            env = {
                "CYBERCHECK_SECURITY_DIR": str(security),
                "CYBERCHECK_INTEGRITY_DIR": str(integrity),
                "CYBERCHECK_GSC_CREDENTIALS_PATH": str(gsc),
                "CYBERCHECK_DATA_DIR": str(data),
                "CYBERCHECK_SITE_CONFIG_PATH": "",
            }
            with mock.patch.dict(os.environ, env, clear=False):
                behavior = runpy.run_path(str(ROOT / "security_behavior.py"))
                alerts = runpy.run_path(str(ROOT / "security_alerts.py"))
                security_integrity = runpy.run_path(str(ROOT / "security_integrity.py"))
                security_ai = runpy.run_path(str(ROOT / "security_ai.py"))
                gsc_client = runpy.run_path(str(ROOT / "gsc_client.py"))
                config_store = runpy.run_path(str(ROOT / "site_config_store.py"))
                runtime_path = config_store["runtime_config_path"]()

            self.assertEqual(behavior["STATE_DIR"], security)
            self.assertEqual(alerts["STATE_DIR"], security)
            self.assertEqual(security_integrity["STATE_DIR"], security)
            self.assertEqual(security_integrity["INTEGRITY_DIR"], integrity)
            self.assertEqual(security_ai["STATE_DIR"], security)
            self.assertEqual(gsc_client["CREDS"], gsc)
            self.assertEqual(runtime_path, data / "site-config.json")

    def test_explicit_site_config_path_overrides_data_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            explicit = root / "custom" / "site.json"
            env = {
                "CYBERCHECK_DATA_DIR": str(root / "data"),
                "CYBERCHECK_SITE_CONFIG_PATH": str(explicit),
            }
            with mock.patch.dict(os.environ, env, clear=False):
                config_store = runpy.run_path(str(ROOT / "site_config_store.py"))
                self.assertEqual(config_store["runtime_config_path"](), explicit)

    def test_shared_host_path_configuration_has_no_import_time_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            security = root / "security"
            integrity = root / "integrity"
            private = root / "private"
            data = root / "data"
            env = {
                "CYBERCHECK_SECURITY_DIR": str(security),
                "CYBERCHECK_INTEGRITY_DIR": str(integrity),
                "CYBERCHECK_GSC_CREDENTIALS_PATH": str(private / "gsc.json"),
                "CYBERCHECK_DATA_DIR": str(data),
            }
            with mock.patch.dict(os.environ, env, clear=False):
                runpy.run_path(str(ROOT / "security_behavior.py"))
                runpy.run_path(str(ROOT / "security_alerts.py"))
                runpy.run_path(str(ROOT / "security_integrity.py"))
                runpy.run_path(str(ROOT / "security_ai.py"))
                runpy.run_path(str(ROOT / "gsc_client.py"))
                runpy.run_path(str(ROOT / "site_config_store.py"))

            self.assertFalse(security.exists())
            self.assertFalse(integrity.exists())
            self.assertFalse(private.exists())
            self.assertFalse(data.exists())


if __name__ == "__main__":
    unittest.main()
