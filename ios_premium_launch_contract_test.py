"""Release-facing iOS surface checks; no simulator is needed for this contract."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCES = ROOT / "ios" / "CheckupAutoReminder" / "Sources"


class IOSPremiumLaunchContractTests(unittest.TestCase):
    def test_unauthenticated_app_opens_premium_welcome_before_dashboard(self):
        app = (SOURCES / "CheckupAutoReminderApp.swift").read_text()
        self.assertIn("if model.customerSignedIn", app)
        self.assertIn("PremiumWelcomeView()", app)
        self.assertIn("ContentView()", app)

    def test_release_dashboard_hides_internal_test_panels_and_loyalty(self):
        screen = (SOURCES / "ContentView.swift").read_text()
        for forbidden in (
            "Tester les notifications",
            "Tester la Dynamic Island",
            "localReminderSection",
            "Scanner mon CT",
            "Rattacher un véhicule ou une cagnotte de test",
            'sectionLabel("FIDÉLITÉ")',
            "loyaltySection",
        ):
            with self.subTest(name=forbidden):
                self.assertNotIn(forbidden, screen)

    def test_direct_mercure_booking_is_premium_full_width(self):
        screen = (SOURCES / "ContentView.swift").read_text()
        urls = (SOURCES / "MobileAPI.swift").read_text()
        self.assertIn("premium-direct-booking", screen)
        self.assertIn("openInApp(MobileAPI.directMercureBookingURL)", screen)
        self.assertIn(".frame(maxWidth: .infinity, minHeight: 106)", screen)
        self.assertIn("https://rdv.checkupauto.fr", urls)

    def test_landing_uses_same_lavis_car_as_website(self):
        website = (ROOT / "index.html").read_text()
        ios_urls = (SOURCES / "MobileAPI.swift").read_text()
        welcome = (SOURCES / "PremiumWelcomeView.swift").read_text()
        artwork = "checkupauto-lavis-option2-1020.webp"
        self.assertIn(artwork, website)
        self.assertIn(artwork, ios_urls)
        self.assertIn("AsyncImage(url: MobileAPI.premiumVehicleArtworkURL())", welcome)

    def test_login_methods_and_registration_are_visible(self):
        options = (SOURCES / "CustomerAuthenticationOptions.swift").read_text()
        email = (SOURCES / "EmailAccountView.swift").read_text()
        for marker in (
            "SignInWithAppleButton",
            "Continuer avec Google",
            "Se connecter par e-mail",
            "Créer un compte par e-mail",
        ):
            self.assertIn(marker, options)
        self.assertIn("EmailCustomerAuthClient.register", email)
        self.assertIn("model.signInWithEmail", email)

    def test_existing_session_is_validated_before_dashboard(self):
        app = (SOURCES / "CheckupAutoReminderApp.swift").read_text()
        model = (SOURCES / "AppModel.swift").read_text()
        client = (SOURCES / "CustomerAccountAPI.swift").read_text()
        self.assertIn("if model.authenticationResolving", app)
        self.assertIn("await restoreCustomerSession()", model)
        self.assertIn("validateStoredSession()", model)
        self.assertIn('/api/mobile/auth/session', client)
        self.assertIn('/api/mobile/account/vehicles', client)

    def test_signed_in_customer_vehicles_do_not_depend_on_installation_binding(self):
        model = (SOURCES / "AppModel.swift").read_text()
        screen = (SOURCES / "ContentView.swift").read_text()
        self.assertIn("CustomerAccountAPI.fetchOwnedVehicles()", model)
        self.assertIn("ForEach(model.accountVehicles)", screen)

    def test_mobile_email_api_uses_native_keychain_not_password_storage(self):
        client = (SOURCES / "EmailCustomerAuth.swift").read_text()
        self.assertIn("CustomerSessionKeychain.save(response.sessionToken)", client)
        self.assertIn('"/api/mobile/auth/email/login"', client)
        self.assertIn('"/api/mobile/auth/email/register"', client)
        self.assertNotIn("UserDefaults", client)


if __name__ == "__main__":
    unittest.main()
