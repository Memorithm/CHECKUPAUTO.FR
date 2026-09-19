import unittest
from pathlib import Path


class MobileClaimAPISurfaceTest(unittest.TestCase):
    def test_only_claim_consumption_is_exposed_over_http(self):
        source = Path("admin_server.py").read_text()
        self.assertIn("/api/mobile/claims/consume", source)
        self.assertIn("consume_vehicle_claim(payload)", source)
        self.assertNotIn("issue_vehicle_claim(", source)

    def test_installation_identity_has_separate_register_and_delete_routes(self):
        source = Path("admin_server.py").read_text()
        self.assertIn("/api/mobile/installations/register", source)
        self.assertIn("register_installation(self._read_json())", source)
        self.assertIn("/api/mobile/installations/delete", source)
        self.assertIn("delete_installation(self._read_json())", source)

    def test_authoritative_sync_is_started_with_server(self):
        source = Path("admin_server.py").read_text()
        self.assertIn("mobile_authoritative_sync.start()", source)


if __name__ == "__main__":
    unittest.main()
