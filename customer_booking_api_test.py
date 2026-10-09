import datetime as dt
import unittest
from unittest.mock import patch

import customer_booking_api as api


class CustomerBookingAPITest(unittest.TestCase):
    def setUp(self):
        self.day=(dt.date.today()+dt.timedelta(days=1)).isoformat()
        self.account={"vehicles":[{"vehicleId":"vehicle-test-1","registration":"AB-123-CD","registrationSystem":"siv","formulaNumberPresent":True,"characteristics":{"brand":"Peugeot","model":"208","energy":"Essence"}}]}
        self.payload={"service":"technical","date":self.day,"time":"10:30","vehicleId":"vehicle-test-1"}

    def test_verified_slot_is_only_preflight_not_booking(self):
        response={"days":[{"date":self.day,"slots":[{"time":"10:30","price":80.0}]}]}
        with patch.object(api.mercure_public_client,"availability",return_value=response) as provider:
            result=api.preflight(self.payload,account=self.account)
        provider.assert_called_once_with("technical",self.day)
        self.assertEqual(result["priceCents"],8000)
        self.assertFalse(result["slotHeld"])
        self.assertFalse(result["bookingConfirmed"])
        self.assertFalse(result["bookingEnabled"])

    def test_rejects_foreign_vehicle_without_provider_call(self):
        with patch.object(api.mercure_public_client,"availability") as provider:
            with self.assertRaisesRegex(api.BookingPreflightError,"booking_vehicle_not_owned"):
                api.preflight({**self.payload,"vehicleId":"other"},account=self.account)
            provider.assert_not_called()

    def test_rejects_unavailable_slot(self):
        with patch.object(api.mercure_public_client,"availability",return_value={"days":[]}):
            with self.assertRaisesRegex(api.BookingPreflightError,"booking_slot_unavailable"):
                api.preflight(self.payload,account=self.account)

    def test_rejects_malformed_inputs(self):
        for override in (
            {"service":"unknown"}, {"time":"25:99"}, {"date":"2020-01-01"},
            {"date":"not-a-date"}, {"vehicleId":""},
        ):
            with self.subTest(override=override), self.assertRaises(api.BookingPreflightError):
                api.preflight({**self.payload,**override},account=self.account)

    def test_rejects_unverified_price(self):
        with patch.object(api.mercure_public_client,"availability",return_value={
            "days":[{"date":self.day,"slots":[{"time":"10:30","price":"80"}]}],
        }):
            with self.assertRaisesRegex(api.BookingPreflightError,"booking_price_unverified"):
                api.preflight(self.payload,account=self.account)


if __name__=="__main__":
    unittest.main()
