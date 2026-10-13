"""Lock the iOS candidate version and the three merged UI corrections."""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parent
IOS=ROOT/"ios/CheckupAutoReminder"


class IOSRelease014Contract(unittest.TestCase):
    def test_new_testflight_build_number_is_monotonic(self):
        spec=(IOS/"project.yml").read_text()
        self.assertIn("CURRENT_PROJECT_VERSION: 17",spec)
        self.assertIn("MARKETING_VERSION: 0.3.14",spec)
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
