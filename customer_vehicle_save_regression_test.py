import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import analytics_store as analytics
import customer_accounts as accounts
import customer_http as http
from customer_http_test import Handler


CHARACTERISTICS = {"brand": "Peugeot", "model": "208", "energy": "Essence"}


class CustomerVehicleSaveRegressionTest(unittest.TestCase):
    """Q-01: saving a vehicle with characteristics must work end to end."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "data").mkdir(); (root / "private").mkdir()
        env = patch.dict(os.environ, {"CYBERCHECK_DATA_DIR": str(root / "data"), "CYBERCHECK_PRIVATE_DIR": str(root / "private")}, clear=False)
        env.start(); self.addCleanup(env.stop)
        previous = analytics.DB
        analytics.DB = root / "analytics.sqlite3"
        self.addCleanup(setattr, analytics, "DB", previous)
        self.account = accounts.create_from_verified_identity("google", "sub-1", "client@example.test", "Client", email_verified=True)

    def test_save_vehicle_with_characteristics_persists_them(self):
        vehicle = accounts.save_vehicle(
            self.account["accountId"], registration_system="siv", registration="aa 123 aa",
            formula_number="2020AB12345", characteristics=dict(CHARACTERISTICS),
        )
        self.assertEqual(vehicle["registration"], "AA-123-AA")
        listed = accounts.list_vehicles(self.account["accountId"])
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["characteristics"]["brand"], "Peugeot")

    def test_missing_booking_essentials_is_a_clean_validation_error(self):
        with self.assertRaisesRegex(accounts.CustomerAccountError, "customer_vehicle_booking_essentials_missing"):
            accounts.save_vehicle(
                self.account["accountId"], registration_system="siv", registration="aa 123 aa",
                formula_number="2020AB12345", characteristics={"brand": "Peugeot", "model": "", "energy": "Essence"},
            )

    def test_dashboard_payload_is_saved_through_http_route(self):
        payload = {
            "vehicleId": "", "registrationSystem": "siv", "registration": "aa 123 aa",
            "formulaNumber": "2020AB12345", "cardIssueDate": "", "characteristics": dict(CHARACTERISTICS),
        }
        h = Handler("/api/customer/vehicles", "POST", payload, headers={"X-CheckupAuto-Customer-CSRF": "c" * 64})
        with patch.object(http, "_account", return_value=("token", self.account)), \
             patch.object(http.customer_accounts, "verify_csrf", return_value=True):
            self.assertTrue(http.handle(h))
        self.assertEqual(h.response["status"], 201, h.response)
        self.assertTrue(h.response["json"]["ok"])
        self.assertEqual(h.response["json"]["vehicles"][0]["characteristics"]["model"], "208")


if __name__ == "__main__":
    unittest.main()
