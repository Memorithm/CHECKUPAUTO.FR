import tempfile
import unittest
from pathlib import Path

import mobile_devices as devices


class MobileDevicesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_dir, self.old_db = devices.DATA_DIR, devices.DB
        devices.DATA_DIR = Path(self.tmp.name); devices.DB = devices.DATA_DIR / "devices.sqlite3"
        devices.init_db()
        self.install_id = "60cf7ccf-4297-41f4-b76b-c0bd44dbe3d1"
        self.secret = "A" * 43
        self.token = "ab" * 32

    def tearDown(self):
        devices.DATA_DIR, devices.DB = self.old_dir, self.old_db
        self.tmp.cleanup()

    def payload(self, **changes):
        data = {"installationId": self.install_id, "registrationSecret": self.secret,
                "deviceToken": self.token, "environment": "sandbox"}
        data.update(changes); return data

    def test_register_keeps_token_private_from_status(self):
        result = devices.register(self.payload())
        self.assertTrue(result["ok"]); self.assertEqual(devices.status()["active"], 1)
        self.assertNotIn(self.token, str(devices.status()))
        self.assertEqual(devices.active_targets()[0]["device_token"], self.token)

    def test_registration_secret_prevents_takeover(self):
        devices.register(self.payload())
        with self.assertRaises(PermissionError):
            devices.register(self.payload(registrationSecret="B" * 43, deviceToken="cd" * 32))
        self.assertEqual(devices.active_targets()[0]["device_token"], self.token)

    def test_unregister_requires_secret_and_clears_raw_token(self):
        devices.register(self.payload())
        with self.assertRaises(PermissionError):
            devices.unregister({"installationId": self.install_id, "registrationSecret": "B" * 43})
        result = devices.unregister({"installationId": self.install_id, "registrationSecret": self.secret})
        self.assertTrue(result["removed"]); self.assertEqual(devices.status()["active"], 0)
        self.assertNotIn(self.token.encode(), devices.DB.read_bytes())

    def test_rejects_malformed_inputs(self):
        with self.assertRaises(ValueError): devices.register(self.payload(installationId="bad"))
        with self.assertRaises(ValueError): devices.register(self.payload(deviceToken="xyz"))
        with self.assertRaises(ValueError): devices.register(self.payload(environment="other"))


if __name__ == "__main__": unittest.main()
