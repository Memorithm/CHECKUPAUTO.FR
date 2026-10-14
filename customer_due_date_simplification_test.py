"""Account UI simplification and server-owned, date-only CT deadline tests.

Runs entirely on temporary data; never uses a real customer account or Mercure.
"""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import analytics_store as analytics
import customer_accounts as accounts
import customer_http as http
from customer_http_test import Handler as WebsiteHandler
from ios_native_vehicle_account_integration_test import Handler as MobileHandler


class DueDateAndDashboardTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "data").mkdir()
        (root / "private").mkdir()
        env = patch.dict(os.environ, {
            "CYBERCHECK_DATA_DIR": str(root / "data"),
            "CYBERCHECK_PRIVATE_DIR": str(root / "private"),
        }, clear=False)
        env.start()
        self.addCleanup(env.stop)
        previous = analytics.DB
        analytics.DB = root / "analytics.sqlite3"
        self.addCleanup(setattr, analytics, "DB", previous)
        self.account = accounts.create_from_verified_identity(
            "google", "ct-date-integration", "vehicle@example.test",
            "Compte test", email_verified=True
        )
        self.account_id = self.account["accountId"]
        self.token = accounts.issue_session(self.account_id)["token"]

    def payload(self):
        return {
            "registrationSystem": "siv",
            "registration": "AA-123-AA",
            "formulaNumber": "2020AB12345",
            "cardIssueDate": "",
            "nextControlDate": "2027-10-14",
            "characteristics": {"brand": "Renault", "model": "Twingo", "energy": "Essence"},
        }

    def test_server_persists_iso_date_in_encrypted_profile_for_site_and_mobile(self):
        vehicle = accounts.save_vehicle(
            self.account_id, registration_system="siv", registration="AA-123-AA",
            formula_number="2020AB12345", next_control_date="2027-10-14",
            characteristics=self.payload()["characteristics"],
        )
        self.assertEqual(vehicle["nextControlDate"], "2027-10-14")
        self.assertEqual(accounts.list_vehicles(self.account_id)[0]["nextControlDate"], "2027-10-14")
        self.assertNotIn(b"2027-10-14", accounts.data_path().read_bytes())
        # Older booking paths omit this field. They must not erase an existing date.
        updated = accounts.save_vehicle(
            self.account_id, vehicle_id=vehicle["vehicleId"],
            registration_system="siv", registration="AA-123-AA",
            formula_number="2020AB12345",
        )
        self.assertEqual(updated["nextControlDate"], "2027-10-14")
        changed = accounts.save_vehicle(
            self.account_id, vehicle_id=vehicle["vehicleId"],
            registration_system="siv", registration="AA-123-AA",
            formula_number="2020AB12345", next_control_date="2028-02-29",
        )
        self.assertEqual(changed["nextControlDate"], "2028-02-29")

    def test_server_rejects_empty_non_iso_invalid_and_nonexistent_dates(self):
        for invalid in ("", "14/10/2027", "2027-2-14", "2027-02-29",
                        "2027-13-14", "1900-02-29", "1899-12-31", "  "):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(
                accounts.CustomerAccountError, "customer_vehicle_next_control_date_invalid"
            ):
                accounts._next_control_date(invalid)
        self.assertEqual(accounts._next_control_date("2028-02-29"), "2028-02-29")
        # An overdue date is still meaningful; the vehicle stays visible.
        self.assertEqual(accounts._next_control_date("2025-09-01"), "2025-09-01")

    def test_mobile_api_requires_deadline_then_site_reads_exact_same_value(self):
        payload = self.payload()
        missing = MobileHandler(http.MOBILE_ACCOUNT_VEHICLE_SAVE_ROUTE,
                                payload={key: value for key, value in payload.items()
                                         if key != "nextControlDate"}, token=self.token)
        http.handle(missing)
        self.assertEqual(missing.response["status"], 422)
        for invalid in (None, "", 20271014, "2027-02-29"):
            with self.subTest(mobile_due_date=invalid):
                bad = MobileHandler(
                    http.MOBILE_ACCOUNT_VEHICLE_SAVE_ROUTE,
                    payload=self.payload() | {"nextControlDate": invalid},
                    token=self.token,
                )
                http.handle(bad)
                self.assertEqual(bad.response["status"], 422)
        self.assertEqual(accounts.list_vehicles(self.account_id), [])
        posted = MobileHandler(http.MOBILE_ACCOUNT_VEHICLE_SAVE_ROUTE,
                               payload=payload, token=self.token)
        http.handle(posted)
        self.assertEqual(posted.response["status"], 201, posted.response)
        self.assertEqual(posted.response["json"]["vehicle"]["nextControlDate"], "2027-10-14")
        self.assertEqual(accounts.list_vehicles(self.account_id)[0]["nextControlDate"], "2027-10-14")
        native_listing = MobileHandler(http.MOBILE_ACCOUNT_VEHICLES_ROUTE, method="GET", token=self.token)
        http.handle(native_listing)
        self.assertEqual(native_listing.response["status"], 200)
        self.assertEqual(native_listing.response["json"]["vehicles"][0]["nextControlDate"], "2027-10-14")
        self.assertNotIn("formulaNumber", native_listing.response["json"]["vehicles"][0])

    def test_web_requires_deadline_and_keeps_csrf_guard(self):
        payload = self.payload() | {"vehicleId": ""}
        with patch.object(http, "_account", return_value=("verified-token", self.account)), \
             patch.object(accounts, "verify_csrf", return_value=True):
            missing = WebsiteHandler(http.VEHICLES_ROUTE, "POST", {
                key: value for key, value in payload.items() if key != "nextControlDate"
            }, headers={"X-CheckupAuto-Customer-CSRF": "c" * 64})
            http.handle(missing)
            self.assertEqual(missing.response["status"], 400)
            for invalid in (None, "", 20271014, "2027-02-29"):
                with self.subTest(web_due_date=invalid):
                    bad = WebsiteHandler(
                        http.VEHICLES_ROUTE, "POST",
                        payload | {"nextControlDate": invalid},
                        headers={"X-CheckupAuto-Customer-CSRF": "c" * 64},
                    )
                    http.handle(bad)
                    self.assertEqual(bad.response["status"], 400)
            self.assertEqual(accounts.list_vehicles(self.account_id), [])
            valid = WebsiteHandler(http.VEHICLES_ROUTE, "POST", payload,
                                   headers={"X-CheckupAuto-Customer-CSRF": "c" * 64})
            http.handle(valid)
            self.assertEqual(valid.response["status"], 201, valid.response)
            self.assertEqual(valid.response["json"]["vehicle"]["nextControlDate"], "2027-10-14")

    def test_dashboard_only_shows_appointments_and_date_input(self):
        # No personal data needed: render against this temporary test account.
        profile = accounts.profile(self.account_id)
        html = http._dashboard_page(self.token, profile, nonce="test-nonce").decode("utf-8")
        self.assertIn("<h2>Rendez-vous</h2>", html)
        self.assertIn("Réserver un contrôle", html)
        for retired in ("Rapports et rendez-vous", "Consulter mes rendez-vous Mercure",
                        'id="ct-report"', 'id="walletToApp"', "PARRAINAGE", "FIDÉLITÉ"):
            with self.subTest(retired=retired):
                self.assertNotIn(retired, html)
        self.assertIn('id="vehicleNextControlDate"', html)
        self.assertIn("JJ/MM/AAAA", html)
        self.assertIn("parseFrenchControlDate", html)
        self.assertIn("Prochain contrôle :", html)
        self.assertNotIn("loadReports();", html)


class IOSAccountDeadlineContracts(unittest.TestCase):
    def test_ios_requires_confirmation_while_preserving_optional_local_reminders(self):
        src = Path(__file__).parent / "ios/CheckupAutoReminder/Sources"
        editor = (src / "AddVehicleView.swift").read_text(encoding="utf-8")
        account = (src / "CustomerAccountAPI.swift").read_text(encoding="utf-8")
        model = (src / "AppModel.swift").read_text(encoding="utf-8")
        home = (src / "ContentView.swift").read_text(encoding="utf-8")
        for fragment in ("controlDateConfirmed &&", "vehicle-confirm-next-control-date",
                         'Locale(identifier: "fr_FR")', "nextControlDate: nextControlDate"):
            self.assertIn(fragment, editor)
        self.assertIn("let nextControlDate: String", account)
        self.assertIn("var nextControlDueDate: Date?", account)
        self.assertIn("let account = accountVehicles.compactMap", model)
        self.assertIn("accountDueDates", model)
        self.assertIn('formatter.dateFormat = withTime ? "dd/MM/yyyy', home)
        self.assertIn("vehicle.nextControlDueDate", home)


if __name__ == "__main__":
    unittest.main()
