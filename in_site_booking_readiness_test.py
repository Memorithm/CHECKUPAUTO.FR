import unittest

from in_site_booking_readiness import BookingCapabilities, declared_capabilities, evaluate


class InSiteBookingReadinessTests(unittest.TestCase):
    def test_public_status_is_explicitly_unavailable_and_no_external_redirect(self):
        from in_site_booking_readiness import public_status
        status = public_status()
        self.assertTrue(status["ok"])
        self.assertTrue(status["bookingOnSiteRequired"])
        self.assertFalse(status["bookingEnabled"])
        self.assertFalse(status["confirmationEnabled"])
        self.assertFalse(status["syntheticAppointmentsAreProduction"])
        self.assertFalse(status["externalMercureRedirectAllowed"])
        self.assertIn("real_mercure_booking_connector_unqualified", status["blockers"])

    def test_current_implementation_cannot_claim_confirmation(self):
        result = evaluate(declared_capabilities())
        self.assertFalse(result["ready"])
        self.assertFalse(result["confirmed"])
        self.assertIn("real_mercure_booking_connector_unqualified", result["missing"])

    def test_payment_not_required_needs_verified_mercure_booking(self):
        capabilities = BookingCapabilities(
            authenticated_customer=True, validated_vehicle=True,
            authoritative_slot=True, real_mercure_write_qualified=True,
            idempotent_reconciliation_qualified=True, appointment_verified=True,
        )
        self.assertTrue(evaluate(capabilities)["confirmed"])

    def test_embedded_payment_must_be_verified_server_side(self):
        common = dict(
            authenticated_customer=True, validated_vehicle=True,
            authoritative_slot=True, real_mercure_write_qualified=True,
            idempotent_reconciliation_qualified=True, appointment_verified=True,
            payment_required=True,
        )
        self.assertFalse(evaluate(BookingCapabilities(**common))["confirmed"])
        self.assertFalse(evaluate(BookingCapabilities(
            **common, embedded_payment_qualified=True,
        ))["confirmed"])
        self.assertTrue(evaluate(BookingCapabilities(
            **common, embedded_payment_qualified=True,
            payment_result_verified=True,
        ))["confirmed"])

    def test_missing_appointment_verification_always_blocks(self):
        capabilities = BookingCapabilities(
            authenticated_customer=True, validated_vehicle=True,
            authoritative_slot=True, real_mercure_write_qualified=True,
            idempotent_reconciliation_qualified=True,
            embedded_payment_qualified=True, payment_result_verified=True,
        )
        self.assertFalse(evaluate(capabilities)["confirmed"])


if __name__ == "__main__":
    unittest.main()
