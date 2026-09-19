import ast
import runpy
import unittest
from unittest import mock
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

    def test_mobile_identity_routes_are_endpoint_rate_limited(self):
        tree = ast.parse(Path("security_guard.py").read_text())
        limits = None
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "_ENDPOINT_LIMITS"
                for target in node.targets
            ):
                limits = ast.literal_eval(node.value)
                break
        self.assertIsNotNone(limits)
        self.assertEqual(limits["/api/mobile/installations/register"], 12)
        self.assertEqual(limits["/api/mobile/installations/delete"], 12)
        self.assertEqual(limits["/api/mobile/claims/consume"], 20)
        self.assertEqual(limits["/api/mobile/reminders/sync"], 30)

    def test_security_behavior_import_is_runtime_side_effect_free(self):
        with mock.patch("sqlite3.connect", side_effect=AssertionError("database opened during import")):
            module = runpy.run_path("security_behavior.py", run_name="security_behavior_import_probe")
        self.assertIn("init_db", module)

    def test_authoritative_sync_is_started_with_server(self):
        source = Path("admin_server.py").read_text()
        self.assertIn("mobile_authoritative_sync.start()", source)


if __name__ == "__main__":
    unittest.main()
