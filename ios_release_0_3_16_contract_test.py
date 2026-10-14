"""Release qualification for iOS 0.3.16 build 19 after VALID 0.3.15 (18)."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent
IOS = ROOT / "ios/CheckupAutoReminder"
SOURCES = IOS / "Sources"


class IOSRelease016Contract(unittest.TestCase):
    def test_exact_monotonic_testflight_release_identity(self):
        spec = (IOS / "project.yml").read_text(encoding="utf-8")
        self.assertIn("CURRENT_PROJECT_VERSION: 19", spec)
        self.assertIn("MARKETING_VERSION: 0.3.16", spec)
        self.assertIn("CHECKUPAUTO_ENVIRONMENT: production", spec)
        notes = (IOS / "RELEASE_NOTES_0.3.16.md").read_text(encoding="utf-8")
        for fragment in ("0.3.16 (19)", "Associer à mon compte",
                         "14 octobre 2027", "WebKit", "TestFlight"):
            self.assertIn(fragment, notes)

    def test_customer_vehicle_parity_is_part_of_the_exact_release(self):
        home = (SOURCES / "ContentView.swift").read_text(encoding="utf-8")
        editor = (SOURCES / "AddVehicleView.swift").read_text(encoding="utf-8")
        account = (SOURCES / "NativeCustomerAccountView.swift").read_text(encoding="utf-8")
        self.assertIn("localVehicleToLink = vehicle", home)
        self.assertIn('account-vehicle-actions', home)
        self.assertIn('Locale(identifier: "fr_FR")', home)
        self.assertIn("CustomerAccountAPI.saveVehicle(payload)", editor)
        self.assertIn("localVehicleToLink.registration", editor)
        self.assertIn("Task { await model.refreshNativeAccount() }", account)
        self.assertIn("AuthenticatedCustomerDashboardWebView(", account)


if __name__ == "__main__":
    unittest.main()
