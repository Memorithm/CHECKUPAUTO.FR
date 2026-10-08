"""Read-only homologation guardrails for the future customer booking flow."""
import unittest
from pathlib import Path

import in_site_booking_readiness as readiness


ROOT = Path(__file__).resolve().parent


class InSiteBookingHomologationTest(unittest.TestCase):
    def test_legacy_redirect_is_not_an_approved_onsite_checkout(self):
        legacy = (ROOT / "booking_bridge.py").read_text(encoding="utf-8")
        self.assertIn("https://rdv.checkupauto.fr/prendre_rdv", legacy)
        status = readiness.public_status()
        self.assertFalse(status["externalMercureRedirectAllowed"])
        self.assertFalse(status["bookingEnabled"])

    def test_synthetic_test_writer_is_not_qualified_for_customers(self):
        writer = (ROOT / "booking_test.py").read_text(encoding="utf-8")
        self.assertIn("create_synthetic_test_appointment", writer)
        self.assertFalse(readiness.public_status()["syntheticAppointmentsAreProduction"])
        self.assertIn(
            "real_mercure_booking_connector_unqualified",
            readiness.public_status()["blockers"],
        )

    def test_missing_embedded_payment_cannot_confirm_paid_booking(self):
        c = readiness.BookingCapabilities(
            authenticated_customer=True, validated_vehicle=True,
            authoritative_slot=True, real_mercure_write_qualified=True,
            idempotent_reconciliation_qualified=True,
            appointment_verified=True, payment_required=True,
            payment_result_verified=True,
        )
        result = readiness.evaluate(c)
        self.assertFalse(result["confirmed"])
        self.assertIn("embedded_mercure_payment_unqualified", result["missing"])


if __name__ == "__main__":
    unittest.main()
