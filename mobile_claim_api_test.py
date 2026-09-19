import unittest
from pathlib import Path


class MobileClaimAPISurfaceTest(unittest.TestCase):
    def test_only_claim_consumption_is_exposed_over_http(self):
        source = Path("admin_server.py").read_text()
        self.assertIn("/api/mobile/claims/consume", source)
        self.assertIn("consume_vehicle_claim(payload)", source)
        self.assertNotIn("issue_vehicle_claim(", source)

    def test_authoritative_sync_is_started_with_server(self):
        source = Path("admin_server.py").read_text()
        self.assertIn("mobile_authoritative_sync.start()", source)


if __name__ == "__main__":
    unittest.main()
