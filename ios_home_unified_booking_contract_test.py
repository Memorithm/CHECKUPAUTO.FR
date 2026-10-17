"""Regression contract: all requested home entry points share the native booking journey."""
import re
import unittest
from pathlib import Path

SOURCE = (
    Path(__file__).resolve().parent
    / "ios/CheckupAutoReminder/Sources/ContentView.swift"
)


class IOSHomeUnifiedBookingContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = SOURCE.read_text(encoding="utf-8")

    def section(self, begin, end):
        self.assertIn(begin, self.home)
        self.assertIn(end, self.home)
        return self.home.split(begin, 1)[1].split(end, 1)[0]

    def test_account_card_is_full_width_and_preserves_signout(self):
        card = self.section("private var appleAccountCard:", "private var hero:")
        self.assertIn('Label("Compte Checkup Auto"', card)
        self.assertIn('Text("Compte connecté")', card)
        self.assertIn('Button("Se déconnecter", role: .cancel)', card)
        self.assertIn("model.signOutCustomer()", card)
        self.assertIn(".frame(maxWidth: .infinity, alignment: .leading)", card)
        self.assertLess(card.index(".frame(maxWidth:"), card.index(".background("))

    def test_toolbar_account_and_plus_open_booking(self):
        toolbar = self.section(".toolbar {", ".onOpenURL")
        for placement, identifier in (
            ("topBarLeading", "home-booking-account-toolbar"),
            ("topBarTrailing", "home-booking-plus-toolbar"),
        ):
            with self.subTest(placement=placement):
                part = toolbar.split("ToolbarItem(placement: ." + placement + ")", 1)[1]
                part = part.split("ToolbarItem(placement:", 1)[0]
                self.assertRegex(part, r"Button\s*\{\s*startBooking\(\)")
                self.assertIn(identifier, part)
                self.assertIn('.accessibilityLabel("Réserver un créneau")', part)

    def test_central_client_action_opens_booking(self):
        actions = self.section("private var quickActions:", "private var nextControlCard:")
        client = actions.split('Text("Espace client")', 1)[0]
        self.assertRegex(client, r"Button\s*\{\s*startBooking\(\)")
        self.assertNotIn("showingNativeAccount = true", actions)

    def test_vehicle_header_plus_opens_booking(self):
        vehicles = self.section("private var vehicleSection:", "private var notificationCard:")
        header = vehicles.split("if model.accountVehicles.isEmpty", 1)[0]
        self.assertRegex(header, r"Button\s*\{\s*startBooking\(\)")
        self.assertIn('Label("Réserver", systemImage: "plus")', header)
        self.assertIn("home-booking-vehicles-plus", header)

    def test_vehicle_registration_remains_accessible(self):
        vehicles = self.section("private var vehicleSection:", "private var notificationCard:")
        self.assertIn('Button("Ajouter un véhicule")', vehicles)
        self.assertIn("showingAddVehicle = true", vehicles)
        self.assertIn(".sheet(isPresented: $showingAddVehicle)", self.home)

    def test_entry_points_keep_identical_session_and_fallback_policy(self):
        flow = self.section("private func startBooking()", "private func daysLabel")
        self.assertIn("if model.customerSignedIn", flow)
        self.assertIn("showingBooking = true", flow)
        self.assertIn("openInApp(MobileAPI.bookingJourneyURL())", flow)
        self.assertIn("BookingJourneyView(onWebFallback:", self.home)


if __name__ == "__main__":
    unittest.main()
