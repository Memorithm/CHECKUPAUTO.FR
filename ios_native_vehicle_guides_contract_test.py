"""Native iOS carte-grise experience must not regress behind website."""
from pathlib import Path
import unittest

import customer_vehicle_inputs as vehicle_rules

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "ios/CheckupAutoReminder/Sources"
IOS_TESTS = ROOT / "ios/CheckupAutoReminder/Tests"


class NativeVehicleGuideContracts(unittest.TestCase):
    def test_native_rules_mirror_site_and_backend(self):
        rules = (SRC / "VehicleRegistrationRules.swift").read_text()
        self.assertIn(vehicle_rules.SIV_PATTERN, rules)
        self.assertIn(vehicle_rules.FNI_PATTERN, rules)
        self.assertIn(vehicle_rules.FORMULA_PATTERN, rules)
        self.assertIn("2009", rules)
        self.assertIn("Aß", (IOS_TESTS / "VehicleRegistrationRulesTests.swift").read_text())
        self.assertIn("static func validDocument(", rules)
        self.assertIn("server", rules)

    def test_card_grise_photographs_are_original_website_assets(self):
        view = (SRC / "AddVehicleView.swift").read_text()
        api = (SRC / "MobileAPI.swift").read_text()
        web = (ROOT / "customer_http.py").read_text()
        for suffix, method in (
            ("carte-grise-formule-photo.webp", "vehicleFormulaGuideURL"),
            ("carte-grise-date-photo.webp", "vehicleCardDateGuideURL"),
        ):
            self.assertTrue((ROOT / "assets/guides" / suffix).is_file())
            self.assertIn(suffix, api)
            self.assertIn(suffix, web)
            self.assertIn(method + "()", view)
        self.assertIn("DisclosureGroup(isExpanded:", view)
        self.assertIn('VehicleRegistrationSystem', view)
        self.assertIn('VehicleRegistrationRules.normalizedRegistration', view)
        self.assertIn('VehicleRegistrationRules.validDocument', view)
        self.assertIn("© Service-Public", view)

    def test_save_is_bound_to_native_customer_account_and_offline_reminder_optional(self):
        view = (SRC / "AddVehicleView.swift").read_text()
        api = (SRC / "CustomerAccountAPI.swift").read_text()
        self.assertIn("CustomerAccountAPI.saveVehicle(payload)", view)
        self.assertIn("await model.refreshNativeAccount()", view)
        self.assertIn("if scheduleReminder {", view)
        self.assertIn("formulaNumber = \"\"", view)
        self.assertNotIn("SFSafariViewController", view)
        self.assertNotIn("openInApp(", view)
        self.assertIn('"/api/mobile/account/vehicles/save"', api)
        self.assertIn('"/api/mobile/account/vehicle-references"', api)
        self.assertIn('request.setValue("Bearer " + token', api)
        self.assertIn("request.cachePolicy = .reloadIgnoringLocalCacheData", api)
        self.assertIn('!model.accountVehicles.contains', (SRC / "ContentView.swift").read_text())

    def test_pure_registration_rules_are_exercised_by_swiftpm_and_xcode(self):
        package = (ROOT / "ios/CheckupAutoReminder/Package.swift").read_text()
        project = (ROOT / "ios/CheckupAutoReminder/project.yml").read_text()
        self.assertIn('"VehicleRegistrationRules.swift"', package)
        self.assertIn('"VehicleRegistrationRulesTests.swift"', package)
        self.assertIn("Tests/VehicleRegistrationRulesTests.swift", project)


if __name__ == "__main__":
    unittest.main()
