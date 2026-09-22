import tempfile
import unittest
from pathlib import Path
from unittest import mock

import mobile_claim_dispatch as dispatch
import mobile_devices


class MobileClaimNamespaceTest(unittest.TestCase):
    def test_dispatch_declares_distinct_reserved_namespaces(self):
        capability = dispatch.capability()
        self.assertEqual(capability["vehicleTokenPrefix"], "vc_")
        self.assertEqual(capability["walletTokenPrefix"], "rw_")
        self.assertTrue(capability["legacyVehicleTokensAccepted"])

    def test_wallet_namespace_never_enters_vehicle_token_validator(self):
        with self.assertRaises(ValueError):
            mobile_devices._claim_token("rw_" + "x" * 43)
        self.assertEqual(
            mobile_devices._claim_token("vc_" + "x" * 43),
            "vc_" + "x" * 43,
        )
        self.assertEqual(mobile_devices._claim_token("x" * 43), "x" * 43)

    def test_new_vehicle_claim_is_prefixed_even_when_entropy_looks_like_wallet_prefix(self):
        original_dir = mobile_devices.DATA_DIR
        original_db = mobile_devices.DB
        with tempfile.TemporaryDirectory() as tmp:
            mobile_devices.DATA_DIR = Path(tmp)
            mobile_devices.DB = Path(tmp) / "mobile-devices.sqlite3"
            try:
                with mock.patch.object(mobile_devices.privacy, "any_suppressed", return_value=False), \
                     mock.patch.object(mobile_devices.secrets, "token_urlsafe", return_value="rw_" + "z" * 40):
                    claim = mobile_devices.issue_vehicle_claim(
                        "vehicle-1",
                        "account",
                        "client-1",
                    )
            finally:
                mobile_devices.DATA_DIR = original_dir
                mobile_devices.DB = original_db

        self.assertTrue(claim["claimToken"].startswith("vc_"))
        self.assertFalse(claim["claimToken"].startswith("rw_"))


if __name__ == "__main__":
    unittest.main()
