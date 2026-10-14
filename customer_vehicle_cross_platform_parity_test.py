"""Cross-platform customer vehicle parity and localization regression checks.

The account inventory is server-owned. Existing iPhone-only reminders must be
explicitly associated after certificate validation, never silently uploaded or
deleted. Both the website and its embedded iOS WebKit view use the same cards.
"""
import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
IOS = ROOT / "ios" / "CheckupAutoReminder" / "Sources"


class CustomerVehicleCrossPlatformParityTests(unittest.TestCase):
    def read_ios(self, name):
        return (IOS / name).read_text(encoding="utf-8")

    def test_site_exposes_accessible_three_dot_actions_with_real_edit_delete(self):
        source = (ROOT / "customer_http.py").read_text(encoding="utf-8")
        ast.parse(source)
        self.assertIn("const more=el('details');more.className='vehicle-more'", source)
        self.assertIn("const toggle=el('summary','•••')", source)
        self.assertIn("toggle.setAttribute('aria-label','Actions pour '+row.registration)", source)
        self.assertIn("editMore.addEventListener('click'", source)
        self.assertIn("editVehicle(row)", source)
        self.assertIn("removeMore.addEventListener('click'", source)
        self.assertIn("removeVehicle(row)", source)
        self.assertIn("vehicle-more-menu", source)
        self.assertIn("X-CheckupAuto-Customer-CSRF", source)
        self.assertIn("customer_accounts.delete_vehicle(account_id", source)

    def test_locally_stored_vehicle_has_explicit_credentialed_link_action(self):
        home = self.read_ios("ContentView.swift")
        add = self.read_ios("AddVehicleView.swift")
        model = self.read_ios("AppModel.swift")
        self.assertIn("localVehicleToLink = vehicle", home)
        self.assertIn('"Associer à mon compte"', home)
        self.assertIn("Sur cet iPhone uniquement · non synchronisé", home)
        self.assertIn("model.customerSignedIn ? {", home)
        self.assertIn("localVehicleToLink.registration", add)
        self.assertIn("normalizedRegistration(", add)
        self.assertIn("localVehicleToLink == nil", add)
        self.assertIn("if scheduleReminder && localVehicleToLink == nil", add)
        self.assertIn("CustomerAccountAPI.saveVehicle(payload)", add)
        self.assertIn("await model.refreshNativeAccount()", add)
        self.assertIn("vehicles.append(vehicle)", model)
        self.assertIn("accountVehicles = vehicles", model)
        self.assertIn("CustomerAccountAPI.fetchOwnedVehicles()", model)
        self.assertNotIn("CustomerAccountAPI.saveVehicle(", model)

    def test_web_account_edits_reload_native_list_without_new_authentication(self):
        home = self.read_ios("ContentView.swift")
        account = self.read_ios("NativeCustomerAccountView.swift")
        bridge = self.read_ios("NativeDashboardBridge.swift")
        self.assertIn('account-vehicle-actions', home)
        self.assertIn('Modifier dans l’espace client', home)
        self.assertIn('Supprimer dans l’espace client', home)
        self.assertIn('Image(systemName: "ellipsis.circle")', home)
        self.assertIn(".onDisappear {", account)
        self.assertIn("Task { await model.refreshNativeAccount() }", account)
        self.assertIn("AuthenticatedCustomerDashboardWebView(", account)
        self.assertIn("NativeDashboardBridge.createBrowserCookie()", account)
        self.assertIn("CustomerSessionKeychain.load()", bridge)

    def test_next_control_month_is_always_french(self):
        home = self.read_ios("ContentView.swift")
        # The stronger numerical format is locale-independent even on an
        # iPhone configured in English; the original verbal month is removed.
        self.assertIn('Text(frenchDate(date))', home)
        self.assertIn('Locale(identifier: "fr_FR")', home)
        self.assertIn('formatter.dateFormat = withTime ? "dd/MM/yyyy', home)
        self.assertIn("model.nextControlDueDate", home)


if __name__ == "__main__":
    unittest.main()
