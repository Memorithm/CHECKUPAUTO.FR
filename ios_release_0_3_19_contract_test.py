"""Version, release notes and booking-routing contract for TestFlight 0.3.19 (22)."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IOS = ROOT / "ios/CheckupAutoReminder"
SOURCES = IOS / "Sources"


class IOSRelease019Contract(unittest.TestCase):
    def test_build22_version_and_release_notes(self):
        spec = (IOS / "project.yml").read_text(encoding="utf-8")
        build = re.search(r"CURRENT_PROJECT_VERSION: (\d+)", spec)
        version = re.search(r"MARKETING_VERSION: (\d+)\.(\d+)\.(\d+)", spec)
        self.assertIsNotNone(build)
        self.assertIsNotNone(version)
        self.assertGreaterEqual(int(build.group(1)), 22)
        self.assertGreaterEqual(tuple(map(int, version.groups())), (0, 3, 19))
        self.assertIn("CHECKUPAUTO_ENVIRONMENT: production", spec)
        notes = (IOS / "RELEASE_NOTES_0.3.19.md").read_text(encoding="utf-8")
        for item in ("0.3.19 (22)", "Mercure", "Payline", "Cloudflare",
                     "test.checkupauto.fr", "RemoteOps", "TestFlight"):
            self.assertIn(item, notes)

    def test_booking_entry_points_use_the_site_in_site_journey(self):
        home = (SOURCES / "ContentView.swift").read_text(encoding="utf-8")
        account = (SOURCES / "NativeCustomerAccountView.swift").read_text(encoding="utf-8")
        # Both booking entry points go through the site's own booking journey,
        # which carries the new in-site Mercure/Payline hosted checkout and is
        # served through the Cloudflare-cached site.
        self.assertIn("openInApp(MobileAPI.bookingJourneyURL())", home)
        self.assertIn("UIApplication.shared.open(MobileAPI.bookingJourneyURL())", account)
        # The legacy "straight to rdv.checkupauto.fr" navigation is gone from
        # both entry points.
        self.assertNotIn("openInApp(MobileAPI.directMercureBookingURL)", home)
        self.assertNotIn("open(MobileAPI.directMercureBookingURL)", account)

    def test_booking_journey_stays_environment_aware(self):
        api = (SOURCES / "MobileAPI.swift").read_text(encoding="utf-8")
        # The journey helper keeps selecting production vs preproduction origin
        # and lands on the public planner anchor.
        self.assertIn("func bookingJourneyURL(", api)
        self.assertIn('components.fragment = "reservation"', api)
        self.assertIn("preproduction ? preproductionBaseURL : productionBaseURL", api)


if __name__ == "__main__":
    unittest.main()
