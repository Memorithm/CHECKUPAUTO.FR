import unittest
from dataclasses import replace

from mercure_booking_identity_evidence import (
    BookingIdentityEvidenceError, VerifiedBookingIdentity, validate_identity,
)


class BookingIdentityEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.evidence=VerifiedBookingIdentity(
            appointment_reference="mercure-123",customer_account_id="customer-1",
            vehicle_id="vehicle-1",service="technical",provider_read_verified=True)
        self.expected=dict(appointment_reference="mercure-123",account_id="customer-1",
                           vehicle_id="vehicle-1",service="technical")

    def test_all_fields_must_match(self):
        self.assertTrue(validate_identity(self.evidence,**self.expected))

    def test_cross_account_vehicle_service_or_reference_mismatch_is_rejected(self):
        for field,value in (
            ("customer_account_id","customer-2"),("vehicle_id","vehicle-2"),
            ("service","fitted"),("appointment_reference","mercure-999"),
        ):
            with self.subTest(field=field),self.assertRaisesRegex(
                BookingIdentityEvidenceError,"booking_identity_mismatch"
            ):
                validate_identity(replace(self.evidence,**{field:value}),**self.expected)

    def test_unverified_and_forged_truthy_flags_are_rejected(self):
        for value in (False,"true",1,None):
            with self.subTest(value=value),self.assertRaisesRegex(
                BookingIdentityEvidenceError,"booking_identity_not_verified"
            ):
                validate_identity(replace(self.evidence,provider_read_verified=value),
                                  **self.expected)


if __name__=="__main__":
    unittest.main()
