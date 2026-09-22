import ast
import runpy
import unittest
from unittest import mock
from pathlib import Path


class MobileClaimAPISurfaceTest(unittest.TestCase):
    def test_shared_claim_consumption_is_exposed_through_typed_dispatch(self):
        source = Path("admin_server.py").read_text()
        self.assertIn("/api/mobile/claims/consume", source)
        self.assertIn("/api/mobile/inventory", source)
        route = source.index("if path=='/api/mobile/claims/consume':")
        end = source.index("if path=='/api/mobile/inventory':", route)
        block = source[route:end]
        self.assertIn("mobile_claim_dispatch.consume_with_authoritative_refresh", block)
        self.assertNotIn("mobile_devices.consume_vehicle_claim", block)
        self.assertNotIn("mobile_authoritative_sync.sync_installation", block)
        self.assertNotIn("issue_vehicle_claim(", source)

    def test_installation_identity_has_separate_register_and_lifecycle_delete_routes(self):
        source = Path("admin_server.py").read_text()
        self.assertIn("/api/mobile/installations/register", source)
        self.assertIn("register_installation(self._read_json())", source)
        delete_route = source.index("if path=='/api/mobile/installations/delete':")
        end = source.index("if path=='/api/mobile/devices/register':", delete_route)
        block = source[delete_route:end]
        self.assertIn("referral_wallet_lifecycle.delete_installation", block)
        self.assertNotIn("mobile_devices.delete_installation", block)

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
        self.assertEqual(limits["/api/mobile/inventory"], 30)
        self.assertEqual(limits["/api/mobile/reminders/sync"], 30)
        self.assertEqual(limits["/api/admin/mobile/claims/issue"], 12)

    def test_mobile_inventory_authenticates_before_authoritative_sync(self):
        source = Path("admin_server.py").read_text()
        route = source.index("if path=='/api/mobile/inventory':")
        end = source.index("if path=='/api/mobile/reminders/sync':", route)
        block = source[route:end]
        auth = block.index("mobile_devices.bound_inventory(payload)")
        sync = block.index("mobile_authoritative_sync.sync_installation")
        self.assertLess(auth, sync)

    def test_admin_claim_issuance_remains_authenticated_and_internal(self):
        source = Path("admin_server.py").read_text()
        admin_guard = source.index("if path.startswith('/api/admin/'):")
        issue_route = source.index("if path=='/api/admin/mobile/claims/issue':")
        self.assertLess(admin_guard, issue_route)
        self.assertIn("mobile_claim_delivery.issue_for_vehicle", source)
        self.assertIn("/api/admin/mobile/claims/candidates", source)
        self.assertNotIn("mobile_devices.issue_vehicle_claim(", source)

    def test_claim_web_surface_has_aasa_and_no_store_landing(self):
        source = Path("admin_server.py").read_text()
        self.assertIn("/.well-known/apple-app-site-association", source)
        self.assertIn("/apple-app-site-association", source)
        self.assertIn("if path=='/app/claim':", source)
        self.assertIn("self._referrer_policy='no-referrer'", source)
        self.assertIn("cache='no-store'", source)

    def test_security_behavior_import_is_runtime_side_effect_free(self):
        with mock.patch("sqlite3.connect", side_effect=AssertionError("database opened during import")):
            module = runpy.run_path("security_behavior.py", run_name="security_behavior_import_probe")
        self.assertIn("init_db", module)

    def test_authoritative_sync_is_started_with_server(self):
        source = Path("admin_server.py").read_text()
        self.assertIn("mobile_authoritative_sync.start()", source)


if __name__ == "__main__":
    unittest.main()
