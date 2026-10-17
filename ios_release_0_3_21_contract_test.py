"""Version, release-notes and behaviour contract for iOS 0.3.21 (24).

0.3.21 builds on the in-app booking journey (0.3.20):
- a flashing, Reduce-Motion-aware native warning shown immediately before the
  external Payline page, telling the customer not to close the app and to come
  back after paying;
- a native planner that can page past the first availability window, up to the
  booking horizon, instead of dead-ending on "no slots";
- a buffered "Réserver" reminder action that still opens the journey after a
  cold launch, once the signed-in screen appears.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IOS = ROOT / "ios/CheckupAutoReminder"
SOURCES = IOS / "Sources"


class IOSRelease021Contract(unittest.TestCase):
    @staticmethod
    def read(path):
        return path.read_text(encoding="utf-8")

    def test_build24_version_and_release_notes(self):
        spec = self.read(IOS / "project.yml")
        build = re.search(r"CURRENT_PROJECT_VERSION: (\d+)", spec)
        version = re.search(r"MARKETING_VERSION: (\d+)\.(\d+)\.(\d+)", spec)
        self.assertIsNotNone(build)
        self.assertIsNotNone(version)
        self.assertGreaterEqual(int(build.group(1)), 24)
        self.assertGreaterEqual(tuple(map(int, version.groups())), (0, 3, 21))
        self.assertIn("CHECKUPAUTO_ENVIRONMENT: production", spec)
        notes = self.read(IOS / "RELEASE_NOTES_0.3.21.md")
        for item in ("0.3.21 (24)", "Payline", "application", "créneaux"):
            self.assertIn(item, notes)

    def test_pre_payline_warning_is_native_animated_and_accessible(self):
        journey = self.read(SOURCES / "BookingJourneyView.swift")
        # A dedicated native step is shown before the Payline page opens.
        self.assertIn("struct PaymentHandoffView", journey)
        self.assertIn("PaymentHandoffView(url:", journey)
        self.assertIn("Ne fermez pas", journey)
        self.assertIn("booking-payment-continue", journey)
        # The flashing is gated behind Reduce Motion for accessibility.
        self.assertIn("accessibilityReduceMotion", journey)
        self.assertIn("repeatForever", journey)
        # Payline still opens in the in-app browser window, after the warning.
        self.assertIn("InAppBrowserView(url:", journey)

    def test_planner_can_page_beyond_the_first_availability_window(self):
        journey = self.read(SOURCES / "BookingJourneyView.swift")
        self.assertIn("func loadMore(", journey)
        self.assertIn("canLoadMore", journey)
        self.assertIn("Afficher plus de créneaux", journey)
        self.assertIn("booking-load-more", journey)
        self.assertIn("MobileAPI.mercureAvailabilityURL(", journey)

    def test_reminder_booking_survives_a_cold_launch(self):
        app = self.read(SOURCES / "CheckupAutoReminderApp.swift")
        content = self.read(SOURCES / "ContentView.swift")
        self.assertIn("enum BookingLaunchIntent", app)
        self.assertIn("BookingLaunchIntent.markPending()", app)
        # The signed-in screen consumes the buffered intent when it appears.
        self.assertIn("BookingLaunchIntent.take()", content)


if __name__ == "__main__":
    unittest.main()
