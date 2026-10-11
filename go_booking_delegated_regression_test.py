"""Regression: with the on-site flag OFF (default), /go/booking is byte-for-byte the
delegated MercureWeb redirect page produced before the on-site journey existed."""
import contextlib
import hashlib
import http.client
import json
import importlib
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

# sha256 of the /go/booking body produced by origin/main 06d6139 with the
# deterministic fixtures below (computed before the on-site journey change).
GOLDEN_SHA256 = "9c3d83bdd1bf98cc45e4c881d17d30ac3fa7383a9c6c1722f78e893d2bf69e2c"
VEHICLE = {"vehicleId": "00000000-0000-4000-8000-0000000000aa", "registrationSystem": "siv",
           "registration": "AB-123-CD"}
QUERY = urlencode({"referrer": "", "utmSource": "", "utmCampaign": "", "device": "desktop",
                   "path": "/", "service": "Contrôle technique",
                   "preferredDate": "2026-12-15", "preferredTime": "09:00"})
ON_SITE_ENV = ("CHECKUPAUTO_IN_SITE_BOOKING_ENABLED", "CHECKUPAUTO_MERCURE_CUSTOMER_WRITE_ENABLED",
               "CHECKUPAUTO_MERCURE_VL_LINE_ID", "CHECKUPAUTO_MERCURE_VL_OPERATOR_ID")


class DelegatedGoBookingRegressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # admin_server and its stores resolve their directories at import time,
        # so a single private/data directory is shared by the whole class.
        cls._dirs = contextlib.ExitStack()
        private = cls._dirs.enter_context(tempfile.TemporaryDirectory())
        data = cls._dirs.enter_context(tempfile.TemporaryDirectory())
        Path(private, "admin-password").write_text("synthetic-test-password\n")
        cls._dirs.enter_context(patch.dict(os.environ, {
            "CYBERCHECK_PRIVATE_DIR": private, "CYBERCHECK_DATA_DIR": data,
            "CYBERCHECK_SECURITY_DIR": str(Path(private, "security"))}))

    @classmethod
    def tearDownClass(cls):
        cls._dirs.close()

    @contextlib.contextmanager
    def server(self, extra_env=None):
        with patch.dict(os.environ, {}):
            for name in ON_SITE_ENV:
                os.environ.pop(name, None)
            os.environ.update(extra_env or {})
            app = importlib.import_module("admin_server")
            booking = app.booking
            app.analytics.init_db()
            app.booking.init_db()
            with app.analytics.connect() as db:  # fixed intent token: start from an empty table
                db.execute("DELETE FROM booking_intents")
            real_token = app.secrets.token_urlsafe
            fixed = {20: "intent-token-000000000001", 18: "nonce-000000000000000001"}

            def token(n=None):
                return fixed.get(n) or real_token(n)
            with patch.object(app.Handler, "_guard", return_value=True), \
                    patch.object(app.customer_http, "consume_booking_confirmation",
                                 return_value={"required": True, "consumed": True,
                                               "confirmedAt": "", "vehicleId": VEHICLE["vehicleId"],
                                               "vehicle": VEHICLE}), \
                    patch.object(booking, "require_published_terms",
                                 return_value={"version": "2026-10-01", "contentHash": "a" * 64}), \
                    patch.object(booking, "preferred_mercure_quote",
                                 return_value={"price": 72.0, "saving": 8.0}), \
                    patch.object(booking, "browser_token", return_value="cct-fixed"), \
                    patch.object(booking, "_checkout_requirements",
                                 return_value={"preferredDate": "2026-12-15", "preferredTime": "09:00",
                                               "requiresImmediatePerformance": False}), \
                    patch.object(booking.secrets, "token_urlsafe", side_effect=token):
                httpd = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
                thread = threading.Thread(target=httpd.serve_forever, daemon=True)
                thread.start()
                try:
                    yield app, httpd.server_address
                finally:
                    httpd.shutdown()
                    httpd.server_close()
                    thread.join(timeout=5)

    def fetch(self, address):
        connection = http.client.HTTPConnection(*address, timeout=10)
        try:
            connection.request("GET", "/go/booking?" + QUERY)
            response = connection.getresponse()
            return response.status, response.getheader("Content-Security-Policy"), response.read()
        finally:
            connection.close()

    def assert_golden(self, body, status=200):
        self.assertEqual(status, 200, body[:600])
        self.assertEqual(hashlib.sha256(body).hexdigest(), GOLDEN_SHA256)
        self.assertNotIn(b"bookingJourneyData", body)

    def test_flag_off_ignores_every_other_switch_and_does_no_extra_io(self):
        env = {"CHECKUPAUTO_MERCURE_CUSTOMER_WRITE_ENABLED": "true",
               "CHECKUPAUTO_MERCURE_VL_LINE_ID": "454", "CHECKUPAUTO_MERCURE_VL_OPERATOR_ID": "464"}
        for flag in (None, "", "false", "1", "TRUE", " true "):
            extra = dict(env)
            if flag is not None:
                extra["CHECKUPAUTO_IN_SITE_BOOKING_ENABLED"] = flag
            with self.subTest(flag=flag), self.server(extra) as (app, address):
                with patch.object(app.booking_readiness, "public_status", side_effect=AssertionError("readiness read")), \
                        patch.object(app.booking_health, "session_status", side_effect=AssertionError("session read")), \
                        patch.object(app.in_site_booking_routing, "decide", side_effect=AssertionError("routing")):
                    status, _, body = self.fetch(address)
                self.assert_golden(body, status)

    def test_flag_on_falls_back_to_identical_delegated_page(self):
        flag = {"CHECKUPAUTO_IN_SITE_BOOKING_ENABLED": "true"}
        cases = {
            "readiness_closed": dict(ready=False, connected=True),
            "mercure_session_invalid": dict(ready=True, connected=False),
            "render_error": dict(ready=True, connected=True, render_error=True),
        }
        for reason, case in cases.items():
            with self.subTest(reason=reason), self.server(flag) as (app, address):
                app.booking_health._reset_for_tests()
                with patch.object(app.in_site_booking_routing.in_site_booking_readiness, "public_status",
                                  return_value={"bookingEnabled": case["ready"]}), \
                        patch.object(app.booking_health, "session_status",
                                     return_value={"connected": case["connected"], "state": "x"}), \
                        patch.object(app.customer_http, "_account", return_value=("t" * 43, {"accountId": "a"})), \
                        patch.object(app.in_site_booking_page, "render_summary",
                                     side_effect=RuntimeError("boom") if case.get("render_error") else AssertionError("must not render")):
                    status, _, body = self.fetch(address)
                self.assert_golden(body, status)
                if reason != "render_error":
                    self.assertEqual(app.booking_health.snapshot()["fallbackReasons"], {reason: 1})

    def test_flag_on_and_ready_renders_on_site_summary_with_delegated_fallback(self):
        account = {"accountId": "00000000-0000-4000-8000-000000000001", "givenName": "Jeanne",
                   "surname": "Martin", "email": "jeanne@example.test", "phone": "0612345678",
                   "billingContactComplete": True}
        with self.server({"CHECKUPAUTO_IN_SITE_BOOKING_ENABLED": "true"}) as (app, address):
            with patch.object(app.in_site_booking_routing.in_site_booking_readiness, "public_status",
                              return_value={"bookingEnabled": True}), \
                    patch.object(app.booking_health, "session_status",
                                 return_value={"connected": True, "state": "ready"}), \
                    patch.object(app.customer_http, "_account", return_value=("t" * 43, account)), \
                    patch.object(app.customer_http.customer_accounts, "csrf_token", return_value="c" * 64):
                status, csp, body = self.fetch(address)
        self.assertEqual(status, 200)
        text = body.decode()
        self.assertNotEqual(hashlib.sha256(body).hexdigest(), GOLDEN_SHA256)
        self.assertIn('id="bookingJourneyData"', text)
        self.assertIn('/assets/booking-journey.js', text)
        # The delegated form is embedded unchanged, but never auto-submitted.
        self.assertIn('action="https://rdv.checkupauto.fr/prendre_rdv?ccid=intent-token-000000000001&amp;cct=cct-fixed"', text)
        self.assertIn('<input type="hidden" name="prestation" value="TOUT VEHICULE HORS CAMPING CAR|1763|80|40|1">', text)
        self.assertNotIn("form.submit()", text)
        self.assertIn("J’ai lu et j’accepte les <a href=\"/cgv\">conditions générales de vente</a>", text)
        self.assertIn("Jeanne Martin", text)
        self.assertIn("AB-123-CD", text)
        data = json.loads(text.split('type="application/json" nonce="nonce-000000000000000001">', 1)[1].split("</script>", 1)[0])
        self.assertEqual(data["service"], "technical")
        self.assertEqual((data["date"], data["time"]), ("2026-12-15", "09:00"))
        self.assertEqual(data["quoteCents"], 7200)
        self.assertEqual(data["vehicleId"], VEHICLE["vehicleId"])
        self.assertEqual(data["csrf"], "c" * 64)
        self.assertIn("nonce-000000000000000001", csp)

    def test_confirmation_page_requires_login_and_valid_key(self):
        with self.server() as (app, address):
            def get(path):
                connection = http.client.HTTPConnection(*address, timeout=5)
                try:
                    connection.request("GET", path)
                    response = connection.getresponse()
                    return response.status, response.getheader("Location"), response.read()
                finally:
                    connection.close()
            self.assertEqual(get("/compte/reservation?cle=" + "k" * 24)[:2], (303, "/compte"))
            with patch.object(app.customer_http, "_account", return_value=("t" * 43, {"accountId": "a"})):
                status, _, body = get("/compte/reservation?cle=" + "k" * 24)
                self.assertEqual(status, 200)
                self.assertIn(b'"requestKey":"' + b"k" * 24 + b'"', body)
                self.assertEqual(get("/compte/reservation?cle=bad")[:2], (303, "/compte"))

    def test_flag_off_body_is_byte_identical_to_previous_delegated_page(self):
        with self.server() as (app, address):
            status, csp, body = self.fetch(address)
        self.assertEqual(status, 200)
        self.assertIn(b"https://rdv.checkupauto.fr/prendre_rdv?ccid=intent-token-000000000001&amp;cct=cct-fixed", body)
        self.assertIn("nonce-000000000000000001", csp)
        self.assertEqual(hashlib.sha256(body).hexdigest(), GOLDEN_SHA256)


if __name__ == "__main__":
    unittest.main()
