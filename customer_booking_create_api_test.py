import unittest
from unittest.mock import patch
import customer_booking_create_api as api

class Tests(unittest.TestCase):
    def setUp(self):
        self.payload=dict(service="technical",date="2026-10-14",time="09:00",
                          vehicleId="vehicle1",requestKey="booking-create-key-00001")

    def test_invalid_idempotency_key(self):
        with self.assertRaises(api.BookingCreateInvalid):
            api.create({**self.payload,"requestKey":"bad"},account={})

    def test_unqualified_writer_does_not_create(self):
        with patch.object(api.customer_booking_api,"preflight",return_value={"bookingEnabled":False}):
            with self.assertRaisesRegex(api.BookingCreateUnavailable,"writer_not_qualified"):
                api.create(self.payload,account={})

    def test_even_ready_flag_cannot_bypass_missing_server_writer(self):
        with patch.object(api.customer_booking_api,"preflight",return_value={"bookingEnabled":True}),patch.object(
            api.in_site_booking_readiness,"public_status",return_value={"bookingEnabled":True}):
            with self.assertRaisesRegex(api.BookingCreateUnavailable,"writer_not_connected"):
                api.create(self.payload,account={})
