"""Qualify the next TestFlight build (after Apple VALID 0.3.14 build 17)."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent
IOS = ROOT / "ios/CheckupAutoReminder"


class IOSRelease015Test(unittest.TestCase):
    def test_version_monotonic_since_valid_build17(self):
        spec = (IOS / "project.yml").read_text()
        self.assertIn("CURRENT_PROJECT_VERSION: 18", spec)
        self.assertIn("MARKETING_VERSION: 0.3.15", spec)
        self.assertIn("CHECKUPAUTO_ENVIRONMENT: production", spec)
        notes = (IOS / "RELEASE_NOTES_0.3.15.md").read_text()
        for item in ("Espace client", "Itinéraire", "48.980120",
                     "1.890251", "0.3.15 (18)", "WebKit"):
            self.assertIn(item, notes)
        self.assertTrue((IOS / "RELEASE_NOTES_0.3.14.md").is_file())

    def test_new_ui_is_present_and_apple_google_authentication_remains_native(self):
        src = IOS / "Sources"
        welcome = (src / "CustomerAuthenticationOptions.swift").read_text()
        self.assertIn("SignInWithAppleButton", welcome)
        self.assertIn("signInWithGoogle()", welcome)
        account = (src / "NativeCustomerAccountView.swift").read_text()
        self.assertIn("AuthenticatedCustomerDashboardWebView(", account)
        self.assertIn("NativeDashboardBridge.createBrowserCookie()", account)
        self.assertIn("centreGPSChoice(isPresented:", account)
        bridge = (src / "NativeDashboardBridge.swift").read_text()
        self.assertIn("HTTPCookie.cookies(", bridge)
        self.assertNotIn("UserDefaults", bridge)


if __name__ == "__main__":
    unittest.main()
