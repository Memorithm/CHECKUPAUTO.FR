"""Version, release notes and in-app booking-journey contract for 0.3.20 (23).

0.3.20 moves the whole booking journey inside the app: a native planner, then
the signed-in in-site Mercure summary and hosted checkout in the app's own
WebKit view (no second login), with only the Payline card page opening in a
window that closes itself. The legacy web journey helper is kept only as a
degraded fallback, and the app never returns to the legacy rdv.checkupauto.fr
Mercure site from its entry points.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IOS = ROOT / "ios/CheckupAutoReminder"
SOURCES = IOS / "Sources"


class IOSRelease020Contract(unittest.TestCase):
    @staticmethod
    def read(path):
        return path.read_text(encoding="utf-8")

    def test_build23_version_and_release_notes(self):
        spec = self.read(IOS / "project.yml")
        build = re.search(r"CURRENT_PROJECT_VERSION: (\d+)", spec)
        version = re.search(r"MARKETING_VERSION: (\d+)\.(\d+)\.(\d+)", spec)
        self.assertIsNotNone(build)
        self.assertIsNotNone(version)
        self.assertGreaterEqual(int(build.group(1)), 23)
        self.assertGreaterEqual(tuple(map(int, version.groups())), (0, 3, 20))
        self.assertIn("CHECKUPAUTO_ENVIRONMENT: production", spec)
        notes = self.read(IOS / "RELEASE_NOTES_0.3.20.md")
        for item in ("0.3.20 (23)", "Mercure", "Payline", "Cloudflare",
                     "application"):
            self.assertIn(item, notes)

    def test_new_in_app_journey_sources_exist_and_are_excluded_from_swiftpm(self):
        manifest = self.read(IOS / "Package.swift")
        for filename in ("AuthenticatedBookingWebView.swift", "BookingJourneyView.swift"):
            self.assertTrue((SOURCES / filename).is_file())
            self.assertIn('"' + filename + '"', manifest)

    def test_mobileapi_exposes_native_planner_and_in_app_entry(self):
        api = self.read(SOURCES / "MobileAPI.swift")
        self.assertIn("/api/booking/services", api)
        self.assertIn("/api/booking/availability", api)
        self.assertIn("func inAppBookingEntryURL(", api)
        # The in-app journey starts on the authenticated passage page that then
        # continues to the in-site /go/booking summary.
        self.assertIn("compte/reserver?returnTo=", api)
        self.assertIn("/go/booking?service=", api)
        self.assertIn("func isHostedPaymentURL(", api)
        self.assertIn("payline.com", api)
        self.assertIn("rdv.checkupauto.fr", api)

    def test_booking_webview_keeps_everything_in_app_except_payline(self):
        view = self.read(SOURCES / "AuthenticatedBookingWebView.swift")
        # Scoped, same-origin, ephemeral WebKit session — never the native bearer.
        self.assertIn("config.websiteDataStore = .nonPersistent()", view)
        self.assertIn("httpCookieStore.setCookie(cookie)", view)
        self.assertNotIn("Bearer ", view)
        # Only the Payline/rdv card page is handed to the system payment sheet.
        self.assertIn("MobileAPI.isHostedPaymentURL(url)", view)
        self.assertIn("parent.onPayment(url)", view)
        self.assertIn("createWebViewWith", view)
        # The hosted-checkout result is observed and surfaced natively.
        self.assertIn("bjHostedDone", view)
        self.assertIn("bjHostedCancelled", view)
        self.assertIn('name: "bookingResult"', view)
        self.assertIn("removeScriptMessageHandler", view)
        # A website login bounce never renders inside the journey.
        self.assertIn("parent.onSessionExpired()", view)

    def test_native_planner_reads_live_mercure_and_payment_window_closes(self):
        journey = self.read(SOURCES / "BookingJourneyView.swift")
        self.assertIn("BookingPlannerLoader", journey)
        self.assertIn("MobileAPI.mercureServicesURL()", journey)
        self.assertIn("MobileAPI.mercureAvailabilityURL(", journey)
        self.assertIn("AuthenticatedBookingWebView(", journey)
        # Only the Payline window uses the in-app browser; it is dismissed as
        # soon as the checkout reports an outcome.
        self.assertIn("InAppBrowserView(url:", journey)
        self.assertIn("payment = nil", journey)
        self.assertIn("BookingOutcome", journey)

    def test_home_entry_point_opens_the_in_app_journey_with_web_fallback(self):
        home = self.read(SOURCES / "ContentView.swift")
        self.assertIn("premium-direct-booking", home)
        self.assertIn("startBooking()", home)
        self.assertIn("BookingJourneyView(", home)
        self.assertIn("showingBooking = true", home)
        # The web journey helper is kept only as the signed-out fallback.
        self.assertIn("openInApp(MobileAPI.bookingJourneyURL())", home)
        # The reminder "Réserver" action opens the in-app journey, not the web.
        self.assertIn("checkupBookingRequested", home)

    def test_account_entry_point_opens_the_in_app_journey_not_the_browser(self):
        account = self.read(SOURCES / "NativeCustomerAccountView.swift")
        self.assertIn("BookingJourneyView(", account)
        self.assertIn("showingBooking = true", account)
        # Fallback to the environment-aware web journey is retained.
        self.assertIn("UIApplication.shared.open(MobileAPI.bookingJourneyURL())", account)
        # The account view itself never leaves for the legacy Mercure site.
        self.assertNotIn("directMercureBookingURL", account)

    def test_reminder_action_requests_the_in_app_journey(self):
        routing = self.read(SOURCES / "NotificationRouting.swift")
        app = self.read(SOURCES / "CheckupAutoReminderApp.swift")
        self.assertIn("checkupBookingRequested", routing)
        self.assertIn("NotificationCenter.default.post(name: .checkupBookingRequested", app)


if __name__ == "__main__":
    unittest.main()
