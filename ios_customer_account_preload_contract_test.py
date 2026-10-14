"""The embedded customer account should not mint a fresh cookie on each open."""
import unittest
from pathlib import Path

SOURCES = Path(__file__).resolve().parent / "ios/CheckupAutoReminder/Sources"


class CustomerAccountPreloadContracts(unittest.TestCase):
    def test_prewarms_when_signed_in_and_keeps_dashboard_in_app(self):
        home = (SOURCES / "ContentView.swift").read_text(encoding="utf-8")
        self.assertIn(".task(id: model.customerSignedIn)", home)
        self.assertIn("await NativeDashboardBridge.prewarm()", home)
        account = (SOURCES / "NativeCustomerAccountView.swift").read_text(encoding="utf-8")
        self.assertIn("AuthenticatedCustomerDashboardWebView(", account)
        self.assertIn("NativeDashboardBridge.createBrowserCookie()", account)
        self.assertIn("NativeDashboardBridge.invalidate()", account)
        self.assertIn("cookieValidUntil = .distantPast", account)

    def test_cookie_cache_is_memory_only_bound_to_native_session(self):
        bridge = (SOURCES / "NativeDashboardBridge.swift").read_text(encoding="utf-8")
        for snippet in (
            "import CryptoKit",
            "private static var cachedCookie: HTTPCookie?",
            "private static var cachedFingerprint: Data?",
            "private static var pendingCookie: Task<HTTPCookie, Error>?",
            "Data(SHA256.hash(data: Data(nativeToken.utf8)))",
            "cachedFingerprint == fingerprint",
            "expiry > Date().addingTimeInterval(120)",
            "CustomerSessionKeychain.load() == nativeToken",
            "private static func issueBrowserCookie(nativeToken: String)",
            "request.httpShouldHandleCookies = false",
            "configuration.httpCookieAcceptPolicy = .never",
            "cookie.isSecure, cookie.isHTTPOnly",
        ):
            self.assertIn(snippet, bridge)
        self.assertNotIn("UserDefaults", bridge)
        self.assertNotIn("FileManager", bridge)

    def test_logout_invalidates_browser_cookie(self):
        model = (SOURCES / "AppModel.swift").read_text(encoding="utf-8")
        self.assertIn(
            "func signOutCustomer() {\n        NativeDashboardBridge.invalidate()\n"
            "        CustomerSessionKeychain.clear()", model,
        )

    def test_ephemeral_webview_still_requires_cookie_installation(self):
        webview = (SOURCES / "AuthenticatedCustomerDashboardWebView.swift").read_text(encoding="utf-8")
        self.assertIn("config.websiteDataStore = .nonPersistent()", webview)
        self.assertIn("httpCookieStore.setCookie(cookie)", webview)
        self.assertIn("webView.load(request)", webview)
        self.assertIn("store.delete($0)", webview)


if __name__ == "__main__":
    unittest.main()
