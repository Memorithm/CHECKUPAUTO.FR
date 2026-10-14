"""Lock the iOS candidate version and the three merged UI corrections."""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parent
IOS=ROOT/"ios/CheckupAutoReminder"


class IOSRelease014Contract(unittest.TestCase):
    def test_new_testflight_build_number_is_monotonic(self):
        spec=(IOS/"project.yml").read_text()
        import re
        version = re.search(r"CURRENT_PROJECT_VERSION: (\d+)", spec)
        marketing = re.search(r"MARKETING_VERSION: (\d+)\.(\d+)\.(\d+)", spec)
        self.assertIsNotNone(version)
        self.assertIsNotNone(marketing)
        self.assertGreaterEqual(int(version.group(1)), 17)
        self.assertGreaterEqual(tuple(map(int, marketing.groups())), (0, 3, 14))
        self.assertIn("CHECKUPAUTO_ENVIRONMENT: production",spec)
        self.assertTrue((IOS/"RELEASE_NOTES_0.3.14.md").is_file())

    def test_native_account_and_vehicle_edits_are_present(self):
        content=(IOS/"Sources/ContentView.swift").read_text()
        self.assertIn("NativeCustomerAccountView()",content)
        self.assertIn("AddVehicleView(isPresented:",content)
        self.assertNotIn("openInApp(model.accountURL)",content)
        self.assertIn("MobileAPI.directMercureBookingURL",content)
        self.assertIn("vehicleFormulaGuideURL()", (IOS/"Sources/AddVehicleView.swift").read_text())
        self.assertIn("sessionRecoveryRequired", (IOS/"Sources/AppModel.swift").read_text())
        self.assertIn("ASWebAuthenticationSession(", (IOS/"Sources/GoogleCustomerSignIn.swift").read_text())


if __name__=="__main__":
    unittest.main()
