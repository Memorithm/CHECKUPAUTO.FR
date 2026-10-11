"""HTTP-level tests for the booking vehicle-mapping fallback (no Mercure access)."""
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

REFS = {"marque": [{"id": "132", "label": "RENAULT"}, {"id": "200", "label": "PEUGEOT"}],
        "energie": [{"id": "2", "label": "DIESEL"}, {"id": "3", "label": "ESSENCE"}]}
MODELS = {"132": [{"id": "1350", "label": "CLIO"}, {"id": "1399", "label": "AUTRES MODELES"}],
          "200": [{"id": "2080", "label": "208"}]}


def models(*, centre_type, brand_id):
    assert centre_type == "1"
    return MODELS[brand_id]


class VehicleMappingHttpTest(unittest.TestCase):
    @contextlib.contextmanager
    def server(self, extra_env=None):
        with tempfile.TemporaryDirectory() as private, tempfile.TemporaryDirectory() as data:
            Path(private, "admin-password").write_text("synthetic-test-password\n")
            env = {"CYBERCHECK_PRIVATE_DIR": private, "CYBERCHECK_DATA_DIR": data,
                   "CYBERCHECK_SECURITY_DIR": str(Path(private, "security")),
                   **(extra_env or {})}
            with patch.dict(os.environ, env):
                os.environ.pop("CHECKUPAUTO_MERCURE_ALLOW_GENERIC_MODEL", None)
                os.environ.update(extra_env or {})
                app = importlib.import_module("admin_server")
                accounts = app.customer_http.customer_accounts
                account = accounts.create_from_verified_identity(
                    "google", "subject-mapping-1", "client@example.test", "Client Test",
                    email_verified=True)
                vehicle = accounts.save_vehicle(
                    account["accountId"], registration_system="siv", registration="AB-123-CD",
                    formula_number="2020AB12345",
                    characteristics={"brand": "Renault Trucks", "model": "Clio V", "energy": "Gazole"})
                mapping = app.customer_http.customer_booking_vehicle_mapping
                with patch.object(app.Handler, "_guard", return_value=True), \
                        patch.object(app.customer_http, "_account", return_value=("tok", account)), \
                        patch.object(accounts, "verify_csrf", side_effect=lambda t, v: v == "c" * 64), \
                        patch.object(mapping.lists, "fetch_references", return_value=REFS), \
                        patch.object(mapping.resolver.lists, "fetch_references", return_value=REFS), \
                        patch.object(mapping.models_api, "models", side_effect=models), \
                        patch.object(mapping.resolver.models_api, "models", side_effect=models):
                    httpd = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
                    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
                    thread.start()
                    try:
                        yield httpd.server_address, account, vehicle, accounts
                    finally:
                        httpd.shutdown()
                        httpd.server_close()
                        thread.join(timeout=5)

    def call(self, address, method, path, body=None, csrf="c" * 64):
        connection = http.client.HTTPConnection(*address, timeout=5)
        headers = {"Origin": f"http://{address[0]}:{address[1]}"}
        raw = None
        if body is not None:
            raw = json.dumps(body).encode()
            headers.update({"Content-Type": "application/json", "Content-Length": str(len(raw)),
                            "X-CheckupAuto-Customer-CSRF": csrf})
        try:
            connection.request(method, path, raw, headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read() or b"{}")
        finally:
            connection.close()

    def test_unmatched_vehicle_is_reported_then_fixed_from_mercure_lists(self):
        with self.server() as (address, account, vehicle, accounts):
            status, body = self.call(address, "GET",
                                     "/api/customer/booking/vehicle-mapping?vehicleId=" + vehicle["vehicleId"])
            self.assertEqual(status, 200)
            self.assertFalse(body["verified"])
            self.assertEqual(body["reason"], "vehicle_reference_missing_or_ambiguous")
            self.assertFalse(body["genericModelAllowed"])

            status, body = self.call(address, "POST", "/api/customer/booking/vehicle-mapping",
                                     {"vehicleId": vehicle["vehicleId"], "brandId": "132",
                                      "modelId": "1350", "energyId": "2"})
            self.assertEqual(status, 200, body)
            self.assertTrue(body["verified"])
            saved = accounts.vehicle_summary(account["accountId"], vehicle["vehicleId"])
            self.assertEqual(saved["characteristics"]["brand"], "RENAULT")
            self.assertEqual(saved["characteristics"]["model"], "CLIO")
            self.assertEqual(saved["characteristics"]["energy"], "DIESEL")
            self.assertEqual(saved["registration"], vehicle["registration"])
            self.assertTrue(saved["formulaNumberPresent"])

    def test_model_from_another_brand_and_unknown_ids_are_refused(self):
        with self.server() as (address, account, vehicle, accounts):
            for body in ({"vehicleId": vehicle["vehicleId"], "brandId": "132", "modelId": "2080", "energyId": "2"},
                         {"vehicleId": vehicle["vehicleId"], "brandId": "999", "modelId": "1350", "energyId": "2"},
                         {"vehicleId": vehicle["vehicleId"], "brandId": "132", "modelId": "1350", "energyId": "x"}):
                with self.subTest(body=body):
                    status, result = self.call(address, "POST", "/api/customer/booking/vehicle-mapping", body)
                    self.assertEqual(status, 422)
                    self.assertEqual(result["error"], "vehicle_reference_selection_invalid")
            saved = accounts.vehicle_summary(account["accountId"], vehicle["vehicleId"])
            self.assertEqual(saved["characteristics"]["brand"], "Renault Trucks")

    def test_generic_model_is_refused_by_default(self):
        with self.server() as (address, account, vehicle, accounts):
            status, result = self.call(address, "POST", "/api/customer/booking/vehicle-mapping",
                                       {"vehicleId": vehicle["vehicleId"], "brandId": "132",
                                        "modelId": "1399", "energyId": "2"})
            self.assertEqual(status, 422)
            self.assertEqual(result["error"], "vehicle_reference_generic_model_unqualified")

    def test_generic_model_is_accepted_only_when_configured(self):
        with self.server({"CHECKUPAUTO_MERCURE_ALLOW_GENERIC_MODEL": "true"}) as (address, account, vehicle, accounts):
            status, result = self.call(address, "POST", "/api/customer/booking/vehicle-mapping",
                                       {"vehicleId": vehicle["vehicleId"], "brandId": "132",
                                        "modelId": "1399", "energyId": "2"})
            self.assertEqual(status, 200, result)
            self.assertTrue(result["verified"])
            self.assertTrue(result["genericModelAllowed"])

    def test_write_requires_csrf_and_same_origin(self):
        with self.server() as (address, account, vehicle, accounts):
            body = {"vehicleId": vehicle["vehicleId"], "brandId": "132", "modelId": "1350", "energyId": "2"}
            status, result = self.call(address, "POST", "/api/customer/booking/vehicle-mapping", body, csrf="bad")
            self.assertEqual((status, result["error"]), (403, "customer_csrf_invalid"))
            saved = accounts.vehicle_summary(account["accountId"], vehicle["vehicleId"])
            self.assertEqual(saved["characteristics"]["model"], "Clio V")

    def test_vehicle_of_another_account_is_not_reachable(self):
        with self.server() as (address, account, vehicle, accounts):
            status, result = self.call(address, "GET",
                                       "/api/customer/booking/vehicle-mapping?vehicleId=00000000-0000-4000-8000-0000000000ff")
            self.assertEqual((status, result["error"]), (422, "booking_vehicle_not_owned"))

    def test_mercure_unavailable_is_a_503_without_change(self):
        with self.server() as (address, account, vehicle, accounts):
            mapping = importlib.import_module("customer_booking_vehicle_mapping")
            with patch.object(mapping.lists, "fetch_references", side_effect=RuntimeError("down")):
                status, result = self.call(address, "POST", "/api/customer/booking/vehicle-mapping",
                                           {"vehicleId": vehicle["vehicleId"], "brandId": "132",
                                            "modelId": "1350", "energyId": "2"})
            self.assertEqual((status, result["error"]), (503, "vehicle_reference_unavailable"))


class ResolverGenericOptionTest(unittest.TestCase):
    def test_generic_model_resolves_only_with_explicit_option(self):
        import mercure_vehicle_reference_resolver as resolver
        with patch.object(resolver.lists, "fetch_references", return_value=REFS), \
                patch.object(resolver.models_api, "models", side_effect=models):
            with self.assertRaises(resolver.VehicleReferenceResolutionError):
                resolver.resolve(brand="Renault", model="Autres modèles", energy="Diesel",
                                 allow_generic_model=False)
            with patch.dict(os.environ, {"CHECKUPAUTO_MERCURE_ALLOW_GENERIC_MODEL": "1"}):
                with self.assertRaises(resolver.VehicleReferenceResolutionError):
                    resolver.resolve(brand="Renault", model="AUTRES MODELES", energy="Diesel")
            result = resolver.resolve(brand="Renault", model="AUTRES MODELES", energy="Diesel",
                                      allow_generic_model=True)
            self.assertEqual(result["modelId"], "1399")


if __name__ == "__main__":
    unittest.main()
