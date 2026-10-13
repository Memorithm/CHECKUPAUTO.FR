"""Authenticated iOS vehicle creation matches the site SIV/FNI rules."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import analytics_store as analytics
import customer_accounts as accounts
import customer_http as http
import security_guard


class Handler:
    def __init__(self, path, method="POST", payload=None, token=None):
        self.path = path
        self.command = method
        self.payload = payload if payload is not None else {}
        self.headers = {"Content-Type": "application/json"}
        if token:
            self.headers["Authorization"] = "Bearer " + token
        self.response = None

    def _read_json(self):
        return self.payload

    def send_json(self, payload, status=200):
        self.response = {"status": status, "json": payload}


class NativeVehicleHttpTests(unittest.TestCase):
    @staticmethod
    def siv(plate="AA-123-AA", formula="2020AB12345"):
        return {
            "registrationSystem": "siv", "registration": plate,
            "formulaNumber": formula, "cardIssueDate": "",
            "characteristics": {"brand": "Peugeot", "model": "208", "energy": "Essence"},
        }

    def test_account_write_rejects_cookie_without_bearer(self):
        handler = Handler(http.MOBILE_ACCOUNT_VEHICLE_SAVE_ROUTE, payload=self.siv())
        handler.headers["Cookie"] = "checkupauto_customer=browser-session"
        with patch.object(http.customer_accounts, "save_vehicle") as write:
            self.assertTrue(http.handle(handler))
            self.assertEqual(handler.response["status"], 401)
            write.assert_not_called()

    def test_write_rejects_cross_site_and_mutating_fields(self):
        handler = Handler(http.MOBILE_ACCOUNT_VEHICLE_SAVE_ROUTE,
                          payload=self.siv(), token="a" * 64)
        handler.headers["Sec-Fetch-Site"] = "cross-site"
        with patch.object(http.customer_accounts, "save_vehicle") as write:
            http.handle(handler)
            self.assertEqual(handler.response["status"], 403)
            write.assert_not_called()
        for payload in (self.siv() | {"accountId": "another"},
                        self.siv() | {"vehicleId": "another-vehicle"},
                        self.siv() | {"characteristics": {"brand": "X", "model": "Y"}},
                        self.siv() | {"characteristics": {"brand": "X", "model": "Y", "energy": "Z", "vin": "private"}}):
            with self.subTest(payload=payload), \
                 patch.object(http.customer_accounts, "authenticate_session", return_value="owned"), \
                 patch.object(http.customer_accounts, "save_vehicle") as write:
                handler = Handler(http.MOBILE_ACCOUNT_VEHICLE_SAVE_ROUTE,
                                  payload=payload, token="a" * 64)
                http.handle(handler)
                self.assertEqual(handler.response["status"], 422)
                write.assert_not_called()

    def test_server_output_omits_formula_and_document_dates(self):
        handler = Handler(http.MOBILE_ACCOUNT_VEHICLE_SAVE_ROUTE,
                          payload=self.siv(), token="a" * 64)
        stored = {
            "vehicleId": "vehicle-1", "registration": "AA-123-AA",
            "registrationSystem": "siv", "formulaNumberPresent": True,
            "formulaNumber": "2020AB12345",
            "characteristics": {"brand": "Peugeot", "model": "208", "energy": "Essence", "vin": "sensitive"},
        }
        with patch.object(http.customer_accounts, "authenticate_session", return_value="owned"), \
             patch.object(http.customer_accounts, "save_vehicle", return_value=stored) as write:
            self.assertTrue(http.handle(handler))
        write.assert_called_once_with(
            "owned", registration_system="siv", registration="AA-123-AA",
            formula_number="2020AB12345", card_issue_date="",
            characteristics={"brand": "Peugeot", "model": "208", "energy": "Essence"},
        )
        self.assertEqual(handler.response["status"], 201)
        self.assertNotIn("formulaNumber", handler.response["json"]["vehicle"])
        self.assertNotIn("vin", str(handler.response["json"]["vehicle"]))
        self.assertNotIn("cardIssueDate", handler.response["json"]["vehicle"])

    def test_references_require_session_and_cannot_fetch_unlisted_brand(self):
        unauthenticated = Handler(http.MOBILE_ACCOUNT_VEHICLE_REFERENCES_ROUTE, method="GET")
        http.handle(unauthenticated)
        self.assertEqual(unauthenticated.response["status"], 401)
        brands = {"marque": [{"id": "12", "label": "Peugeot"}],
                  "energie": [{"id": "5", "label": "Essence"}]}
        handler = Handler(http.MOBILE_ACCOUNT_VEHICLE_REFERENCES_ROUTE + "?brandId=99",
                          method="GET", token="b" * 64)
        with patch.object(http.customer_accounts, "authenticate_session", return_value="owned"), \
             patch.object(http.mercure_brand_energy_reference, "fetch_references", return_value=brands), \
             patch.object(http.mercure_vehicle_reference, "models") as models:
            http.handle(handler)
        self.assertEqual(handler.response["status"], 422)
        models.assert_not_called()

    def test_references_reuse_site_verified_catalog(self):
        handler = Handler(http.MOBILE_ACCOUNT_VEHICLE_REFERENCES_ROUTE + "?brandId=12",
                          method="GET", token="b" * 64)
        brands = {"marque": [{"id": "12", "label": "Peugeot"}],
                  "energie": [{"id": "5", "label": "Essence"}]}
        with patch.object(http.customer_accounts, "authenticate_session", return_value="owned"), \
             patch.object(http.mercure_brand_energy_reference, "fetch_references", return_value=brands), \
             patch.object(http.mercure_vehicle_reference, "models", return_value=[
                 {"id": "208", "label": "208"}
             ]) as models:
            http.handle(handler)
        self.assertEqual(handler.response["status"], 200)
        self.assertEqual(handler.response["json"]["brands"], brands["marque"])
        self.assertEqual(handler.response["json"]["models"], [{"id": "208", "label": "208"}])
        models.assert_called_once_with(centre_type="1", brand_id="12")

    def test_rates_cover_native_document_endpoint(self):
        self.assertLessEqual(security_guard._ENDPOINT_LIMITS[http.MOBILE_ACCOUNT_VEHICLE_REFERENCES_ROUTE], 20)
        self.assertLessEqual(security_guard._ENDPOINT_LIMITS[http.MOBILE_ACCOUNT_VEHICLE_SAVE_ROUTE], 8)


class NativeVehiclePersistenceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "data").mkdir()
        (root / "private").mkdir()
        env = patch.dict(os.environ, {
            "CYBERCHECK_DATA_DIR": str(root / "data"),
            "CYBERCHECK_PRIVATE_DIR": str(root / "private")
        }, clear=False)
        env.start()
        self.addCleanup(env.stop)
        before = analytics.DB
        analytics.DB = root / "analytics.sqlite3"
        self.addCleanup(setattr, analytics, "DB", before)
        account = accounts.create_from_verified_identity(
            "google", "mobile-native-vehicle", "ios@example.test",
            "Cliente", email_verified=True
        )
        self.account_id = account["accountId"]
        self.token = accounts.issue_session(self.account_id)["token"]

    def test_siv_account_vehicle_exists_on_site_after_native_save(self):
        handler = Handler(http.MOBILE_ACCOUNT_VEHICLE_SAVE_ROUTE,
                          payload=NativeVehicleHttpTests.siv(), token=self.token)
        http.handle(handler)
        self.assertEqual(handler.response["status"], 201, handler.response)
        site = accounts.list_vehicles(self.account_id)
        self.assertEqual(len(site), 1)
        self.assertEqual(site[0]["registration"], "AA-123-AA")
        self.assertEqual(site[0]["characteristics"]["model"], "208")
        self.assertTrue(site[0]["formulaNumberPresent"])
        self.assertNotIn("formulaNumber", str(handler.response["json"]))

    def test_fni_requires_document_issue_date_without_formula(self):
        payload = NativeVehicleHttpTests.siv(plate="1234 AB 78", formula="")
        payload.update(registrationSystem="fni", cardIssueDate="2020-02-11")
        handler = Handler(http.MOBILE_ACCOUNT_VEHICLE_SAVE_ROUTE,
                          payload=payload, token=self.token)
        http.handle(handler)
        self.assertEqual(handler.response["status"], 201, handler.response)
        self.assertEqual(accounts.list_vehicles(self.account_id)[0]["cardIssueDate"], "2020-02-11")

    def test_invalid_plate_is_denied_by_backend_even_if_client_skipped_validation(self):
        handler = Handler(http.MOBILE_ACCOUNT_VEHICLE_SAVE_ROUTE,
                          payload=NativeVehicleHttpTests.siv(plate="SS-000-AA"),
                          token=self.token)
        http.handle(handler)
        self.assertEqual(handler.response["status"], 422)
        self.assertEqual(accounts.list_vehicles(self.account_id), [])


if __name__ == "__main__":
    unittest.main()
