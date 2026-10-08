import datetime as dt
import unittest
from dataclasses import replace

from mercure_booking_write_contract import BookingWriteRequest
from mercure_booking_write_validation import BookingWriteValidationError, validate


class MercureBookingWriteValidationTests(unittest.TestCase):
    def setUp(self):
        self.request=BookingWriteRequest(
            request_key="booking-key-00000000001",account_id="customer-1",
            vehicle_id="vehicle-1",service="technical",
            date="2026-10-15",time="10:30",price_cents=8000)

    def test_valid_payload_is_preserved(self):
        self.assertEqual(validate(self.request,today=dt.date(2026,10,8)),self.request)

    def test_invalid_values_are_rejected_without_normalizing_or_guessing(self):
        invalid=[
            {"request_key":"x"},{"account_id":"../other"},{"vehicle_id":""},
            {"service":"free"},{"date":"2020-01-01"},{"date":"2027-01-01"},
            {"time":"25:99"},{"price_cents":True},{"price_cents":-1},
            {"price_cents":1.5},{"price_cents":1000001},
        ]
        for fields in invalid:
            with self.subTest(fields=fields), self.assertRaises(BookingWriteValidationError):
                validate(replace(self.request,**fields),today=dt.date(2026,10,8))


if __name__=="__main__":
    unittest.main()
