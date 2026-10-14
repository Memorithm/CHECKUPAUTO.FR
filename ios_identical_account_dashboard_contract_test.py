"""Website-identical iOS account and centre navigation regression contract."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent
IOS = ROOT / "ios/CheckupAutoReminder"
SOURCES = IOS / "Sources"


class IOSPixelIdenticalDashboardTests(unittest.TestCase):
    @staticmethod
    def read(path):
        return path.read_text(encoding="utf-8")

    def test_authenticated_account_uses_actual_first_party_website_not_a_clone(self):
        account = self.read(SOURCES / "NativeCustomerAccountView.swift")
        webkit = self.read(SOURCES / "AuthenticatedCustomerDashboardWebView.swift")
        html = self.read(ROOT / "customer_http.py")
        self.assertIn("AuthenticatedCustomerDashboardWebView(", account)
        self.assertIn('MobileAPI.endpoint("/compte")', webkit)
        self.assertIn("WKWebView(frame: .zero, configuration: config)", webkit)
        self.assertIn("config.websiteDataStore = .nonPersistent()", webkit)
        self.assertIn("httpCookieStore.setCookie(cookie)", webkit)
        self.assertIn("webView.load(request)", webkit)
        self.assertNotIn("SFSafariViewController", account + webkit)
        self.assertIn("Vos véhicules enregistrés", html)
        self.assertIn("IMMATRICULATION SIV", html)
        self.assertIn("IMMATRICULATION FNI", html)
        self.assertIn("Réserver un contrôle", html)
        self.assertIn("Modifier", html)
        self.assertIn("Supprimer", html)
        self.assertIn("vehicle-card", html)
        self.assertIn("CHECKUPAUTO", html)

    def test_bearer_credential_never_enters_webkit_or_url(self):
        bridge = self.read(SOURCES / "NativeDashboardBridge.swift")
        view = self.read(SOURCES / "AuthenticatedCustomerDashboardWebView.swift")
        server = self.read(ROOT / "customer_http.py")
        self.assertIn('"/api/mobile/auth/web-session"', bridge)
        self.assertIn('request.setValue("Bearer " + nativeToken', bridge)
        self.assertIn("request.httpShouldHandleCookies = false", bridge)
        self.assertIn("URLSessionConfiguration.ephemeral", bridge)
        self.assertIn("httpCookieAcceptPolicy = .never", bridge)
        self.assertIn("completionHandler(nil)", bridge)
        self.assertIn("cookie.isSecure, cookie.isHTTPOnly", bridge)
        self.assertIn('request.cachePolicy = .reloadIgnoringLocalCacheData', view)
        self.assertNotIn("Bearer ", view)
        self.assertIn('"HttpOnly; Secure; SameSite=Lax"', server)
        self.assertIn("lifetime_seconds=3600", server)
        self.assertIn("headers={", server)
        self.assertIn("Set-Cookie", server)

    def test_buttons_and_account_actions_remain_operational_in_webkit(self):
        view = self.read(SOURCES / "AuthenticatedCustomerDashboardWebView.swift")
        parent = self.read(SOURCES / "NativeCustomerAccountView.swift")
        self.assertIn("runJavaScriptConfirmPanelWithMessage", view)
        self.assertIn("completionHandler(true)", view)
        self.assertIn('url.path == "/compte/deconnexion"', view)
        self.assertIn("parent.onSignOut()", view)
        self.assertIn("parent.onBooking()", view)
        self.assertIn('url.path == "/go/booking"', view)
        self.assertIn('url.path == "/app/claim"', view)
        self.assertIn("parent.onClaim(url)", view)
        self.assertIn('url.path == "/compte"', view)
        self.assertIn("onSessionExpired()", view)
        self.assertIn("onNavigationBlocked()", view)
        self.assertIn("model.signOutCustomer()", parent)
        self.assertIn("model.consumeMobileClaim(url: url)", parent)
        self.assertIn("MobileAPI.directMercureBookingURL", parent)
        self.assertIn("cookieValidUntil", parent)
        self.assertIn("openAccountWebsite() async", parent)

    def test_site_gps_destination_is_shared_exactly_with_ios_and_available_from_account(self):
        website = self.read(ROOT / "index.html")
        chooser = self.read(SOURCES / "CentreGPSChoice.swift")
        account = self.read(SOURCES / "NativeCustomerAccountView.swift")
        home = self.read(SOURCES / "ContentView.swift")
        project = self.read(IOS / "project.yml")

        self.assertIn("1E rue Niépce, 78130 Les Mureaux", website)
        self.assertIn("1E rue Niépce, 78130 Les Mureaux", chooser)
        self.assertIn("48.980120", website)
        self.assertIn("1.890251", website)
        self.assertIn("48.980120", chooser)
        self.assertIn("1.890251", chooser)
        self.assertIn("Plans d’Apple", chooser)
        self.assertIn("Google Maps", chooser)
        self.assertIn("Waze", chooser)
        self.assertIn("MKLaunchOptionsDirectionsModeDriving", chooser)
        self.assertIn("canOpenURL(CheckupAutoCentre.googleMapsURL)", chooser)
        self.assertIn("canOpenURL(CheckupAutoCentre.wazeURL)", chooser)
        self.assertIn("LSApplicationQueriesSchemes:", project)
        self.assertIn("  - comgooglemaps", project)
        self.assertIn("  - waze", project)
        self.assertIn("native-account-gps", account)
        self.assertIn("native-journey-gps-choice", home)
        self.assertIn("centreGPSChoice(isPresented:", account)
        self.assertIn("centreGPSChoice(isPresented:", home)
        self.assertNotIn("requestWhenInUseAuthorization", chooser)

    def test_swiftpm_excludes_app_only_webkit_and_gps_sources(self):
        manifest = self.read(IOS / "Package.swift")
        for filename in (
            "NativeDashboardBridge.swift",
            "AuthenticatedCustomerDashboardWebView.swift",
            "CentreGPSChoice.swift",
        ):
            self.assertIn('"' + filename + '"', manifest)


if __name__ == "__main__":
    unittest.main()
