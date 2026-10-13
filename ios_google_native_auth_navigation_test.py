"""Native Google OAuth consent and account-help navigation contracts."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent / "ios/CheckupAutoReminder/Sources"


class GoogleAuthenticationNativeNavigationTests(unittest.TestCase):
    def test_google_uses_system_owned_secure_oauth_not_embedded_wkwebview(self):
        client = (ROOT / "GoogleCustomerSignIn.swift").read_text()
        buttons = (ROOT / "CustomerAuthenticationOptions.swift").read_text()
        self.assertIn("ASWebAuthenticationSession(", client)
        self.assertIn('callbackURLScheme: "checkupauto"', client)
        self.assertIn('code_challenge', client)
        self.assertIn('"code_verifier"', client)
        self.assertIn('CustomerSessionKeychain.save(token)', client)
        self.assertIn('auth.presentationContextProvider = self', client)
        self.assertNotIn("WKWebView", client)
        self.assertNotIn("SFSafariViewController", client)
        self.assertIn("fenêtre sécurisée iOS", buttons)
        self.assertIn('premium-auth-google-system-explanation', buttons)

    def test_only_in_app_account_help_sheets_without_external_safari_link(self):
        view = (ROOT / "EmailAccountView.swift").read_text()
        self.assertIn("AccountHelpPage(url: MobileAPI.endpoint", view)
        self.assertIn(".sheet(item: $helpPage)", view)
        self.assertIn("InAppBrowserView(url: destination.url)", view)
        self.assertNotIn('Link("Consulter la politique de confidentialité"', view)
        self.assertNotIn('Link("Mot de passe oublié ?" ', view)


if __name__ == "__main__":
    unittest.main()
