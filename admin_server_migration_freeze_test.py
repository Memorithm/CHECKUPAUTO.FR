import unittest
from unittest import mock

import admin_server
import security_integrity


class AdminServerMigrationFreezeTest(unittest.TestCase):
    def handler(self, command="POST"):
        handler=admin_server.Handler.__new__(admin_server.Handler)
        handler.command=command
        handler.path="/contact"
        handler._security_checked=False
        handler.responses=[]

        def send_json(body,status=200,headers=None):
            handler.responses.append({
                "body":body,
                "status":status,
                "headers":dict(headers or {}),
            })

        handler.send_json=send_json
        return handler

    def test_active_freeze_blocks_mutating_direct_runtime_request(self):
        handler=self.handler("POST")
        with mock.patch(
            "admin_server.migration_write_freeze.status",
            return_value={"active":True,"valid":True,"state":"frozen"},
        ):
            self.assertFalse(handler._migration_write_allowed())
        self.assertEqual(handler.responses,[{
            "body":{"ok":False,"error":"migration_write_frozen"},
            "status":503,
            "headers":{
                "Retry-After":"120",
                "X-CheckupAuto-Migration-Freeze":"active",
            },
        }])

    def test_invalid_marker_still_fails_closed(self):
        handler=self.handler("DELETE")
        with mock.patch(
            "admin_server.migration_write_freeze.status",
            return_value={"active":True,"valid":False,"state":"invalid_marker"},
        ):
            self.assertFalse(handler._migration_write_allowed())
        self.assertEqual(handler.responses[0]["status"],503)

    def test_freeze_probe_failure_fails_closed(self):
        handler=self.handler("POST")
        with mock.patch(
            "admin_server.migration_write_freeze.status",
            side_effect=OSError("unavailable"),
        ):
            self.assertFalse(handler._migration_write_allowed())
        self.assertEqual(handler.responses[0]["body"]["error"],"migration_write_frozen")

    def test_safe_methods_remain_readable_without_touching_freeze_state(self):
        for method in ("GET","HEAD","OPTIONS"):
            with self.subTest(method=method):
                handler=self.handler(method)
                with mock.patch("admin_server.migration_write_freeze.status") as status:
                    self.assertTrue(handler._migration_write_allowed())
                status.assert_not_called()
                self.assertEqual(handler.responses,[])

    def test_guard_stops_mutations_before_security_or_route_handlers(self):
        handler=self.handler("POST")
        with mock.patch(
            "admin_server.migration_write_freeze.status",
            return_value={"active":True,"valid":True,"state":"frozen"},
        ), mock.patch("admin_server.security.evaluate") as evaluate:
            self.assertFalse(handler._guard())
        evaluate.assert_not_called()
        self.assertFalse(handler._security_allowed)

    def test_freeze_gate_is_runtime_integrity_critical(self):
        self.assertIn("migration_write_freeze.py",security_integrity.CRITICAL_FILES)


if __name__=="__main__":
    unittest.main()
