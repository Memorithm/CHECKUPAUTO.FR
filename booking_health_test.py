"""Booking health signals: create-route outcomes, Mercure session check, admin view."""
import base64
import contextlib
import http.client
import importlib
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import booking_health

ACCOUNT = {"accountId": "00000000-0000-4000-8000-000000000001", "email": "client@example.test"}
BODY = {"service": "technical", "date": "2026-10-15", "time": "09:00",
        "vehicleId": "00000000-0000-4000-8000-0000000000aa", "requestKey": "k" * 24}
FLAG = "CHECKUPAUTO_IN_SITE_BOOKING_ENABLED"


class BookingHealthHttpTest(unittest.TestCase):
    def setUp(self):
        booking_health._reset_for_tests()

    @contextlib.contextmanager
    def server(self, flag=None):
        with tempfile.TemporaryDirectory() as private, tempfile.TemporaryDirectory() as data:
            Path(private, "admin-password").write_text("synthetic-test-password\n")
            env = {"CYBERCHECK_PRIVATE_DIR": private, "CYBERCHECK_DATA_DIR": data,
                   "CYBERCHECK_SECURITY_DIR": str(Path(private, "security"))}
            with patch.dict(os.environ, env):
                os.environ.pop(FLAG, None)
                if flag is not None:
                    os.environ[FLAG] = flag
                app = importlib.import_module("admin_server")
                ch = app.customer_http
                with patch.object(app.Handler, "_guard", return_value=True), \
                        patch.object(ch, "_account", return_value=("tok", ACCOUNT)), \
                        patch.object(ch.customer_accounts, "verify_csrf", return_value=True), \
                        patch.object(ch.customer_accounts, "list_vehicles", return_value=[]), \
                        patch("security_alerts.emit") as emit:
                    httpd = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
                    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
                    thread.start()
                    try:
                        yield app, httpd.server_address, emit
                    finally:
                        httpd.shutdown()
                        httpd.server_close()
                        thread.join(timeout=5)

    def post_create(self, address):
        raw = json.dumps(BODY).encode()
        connection = http.client.HTTPConnection(*address, timeout=5)
        try:
            connection.request("POST", "/api/customer/booking/create", raw, {
                "Content-Type": "application/json", "Content-Length": str(len(raw)),
                "Origin": f"http://{address[0]}:{address[1]}",
                "X-CheckupAuto-Customer-CSRF": "c" * 64})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_default_disabled_create_is_counted_without_alert(self):
        with self.server() as (app, address, emit):
            status, body = self.post_create(address)
        self.assertEqual((status, body["error"]), (503, "booking_provider_not_qualified"))
        self.assertEqual(booking_health.snapshot()["counters"]["disabled"], 1)
        self.assertEqual(booking_health.snapshot()["counters"]["providerFailures"], 0)
        emit.assert_not_called()

    def test_provider_failure_alerts_only_when_flag_is_on(self):
        for flag, expected in ((None, 0), ("true", 1)):
            booking_health._reset_for_tests()
            with self.subTest(flag=flag), self.server(flag) as (app, address, emit):
                ctx = app.customer_http.customer_booking_http_trusted_context
                with patch.object(ctx, "prepare",
                                  side_effect=ctx.BookingHttpContextError("booking_payment_policy_unqualified")):
                    status, body = self.post_create(address)
                self.assertEqual((status, body["error"]), (503, "booking_provider_not_qualified"))
                self.assertEqual(booking_health.snapshot()["counters"]["providerFailures"], 1)
                self.assertEqual(emit.call_count, expected)
                if expected:
                    self.assertEqual(emit.call_args.args[1], "booking_mercure_write")
                    self.assertNotIn("client@example.test", json.dumps(emit.call_args.args, ensure_ascii=False))

    def test_reconciliation_required_is_counted_and_alerted(self):
        with self.server("true") as (app, address, emit):
            ch = app.customer_http
            with patch.object(ch.customer_booking_http_trusted_context, "prepare", return_value=(object(), {})), \
                    patch.object(ch.customer_booking_create_api, "create",
                                 return_value={"ok": True, "confirmed": False, "state": "reconciliation_required"}):
                status, body = self.post_create(address)
        self.assertEqual((status, body["state"]), (200, "reconciliation_required"))
        self.assertEqual(booking_health.snapshot()["counters"]["reconciliationRequired"], 1)
        self.assertEqual(emit.call_args.args[1], "booking_mercure_reconciliation")

    def test_slot_lost_is_not_a_provider_failure(self):
        with self.server("true") as (app, address, emit):
            ch = app.customer_http
            with patch.object(ch.customer_booking_http_trusted_context, "prepare", return_value=(object(), {})), \
                    patch.object(ch.customer_booking_create_api, "create",
                                 side_effect=ch.customer_booking_create_api.BookingCreateInvalid("booking_slot_unavailable")):
                status, body = self.post_create(address)
        self.assertEqual((status, body["error"]), (422, "booking_slot_unavailable"))
        self.assertEqual(booking_health.snapshot()["counters"]["slotLost"], 1)
        emit.assert_not_called()

    def test_admin_view_requires_auth_and_reports_session(self):
        with self.server() as (app, address, emit):
            with patch.object(app.admin_mfa, "configured", return_value=False), \
                    patch.object(app.admin_mfa, "required", return_value=False), \
                    patch.object(app.mercure_admin, "session_status",
                                 return_value={"connected": False, "state": "session_unavailable"}):
                connection = http.client.HTTPConnection(*address, timeout=5)
                connection.request("GET", "/api/admin/mercure/booking-health")
                anonymous = connection.getresponse()
                anonymous.read()
                connection.close()
                token = base64.b64encode(f"{app.USER}:{app.PASSWORD}".encode()).decode()
                connection = http.client.HTTPConnection(*address, timeout=5)
                connection.request("GET", "/api/admin/mercure/booking-health?refresh=1",
                                   headers={"Authorization": "Basic " + token})
                response = connection.getresponse()
                body = json.loads(response.read())
                connection.close()
        self.assertEqual(anonymous.status, 401)
        self.assertEqual(response.status, 200)
        self.assertFalse(body["readiness"]["bookingEnabled"])
        self.assertEqual(body["session"]["state"], "session_unavailable")
        self.assertFalse(body["health"]["alertsActive"])
        emit.assert_not_called()


class SessionCacheTest(unittest.TestCase):
    def setUp(self):
        booking_health._reset_for_tests()

    def test_session_check_is_cached_and_alerts_only_with_flag(self):
        calls = []

        def checker():
            calls.append(1)
            return {"connected": False, "state": "session_unavailable"}

        with patch.dict(os.environ, {FLAG: "true"}), \
                patch("security_alerts.emit") as emit:
            first = booking_health.session_status(checker=checker)
            second = booking_health.session_status(checker=checker)
        self.assertFalse(first["connected"])
        self.assertEqual(second["state"], "session_unavailable")
        self.assertEqual(len(calls), 1)
        self.assertEqual(emit.call_args.args[1], "booking_mercure_session")

        booking_health._reset_for_tests()
        env = {k: v for k, v in os.environ.items() if k != FLAG}
        with patch.dict(os.environ, env, clear=True), patch("security_alerts.emit") as emit:
            booking_health.session_status(checker=checker)
        emit.assert_not_called()

    def test_checker_exception_is_reported_not_raised(self):
        def checker():
            raise RuntimeError("boom")
        result = booking_health.session_status(checker=checker, refresh=True)
        self.assertEqual(result, {"connected": False, "state": "unexpected_error",
                                  "checkedAt": result["checkedAt"]})

    def test_connected_session_does_not_alert(self):
        with patch.dict(os.environ, {FLAG: "true"}), patch("security_alerts.emit") as emit:
            result = booking_health.session_status(checker=lambda: {"connected": True, "state": "ready"})
        self.assertTrue(result["connected"])
        emit.assert_not_called()

    def test_classification(self):
        self.assertEqual(booking_health.classify("booking_writer_not_qualified"), "disabled")
        self.assertEqual(booking_health.classify("booking_slot_unavailable"), "slotLost")
        self.assertEqual(booking_health.classify("booking_vehicle_not_owned"), "customerErrors")
        self.assertEqual(booking_health.classify("mercure_write_outcome_uncertain"), "providerFailures")


if __name__ == "__main__":
    unittest.main()
