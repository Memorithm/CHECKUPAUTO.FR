import unittest
from customer_vehicle_characteristics import require_booking_essentials,VehicleCharacteristicsError,normalize


class VehicleBookingEssentialsTests(unittest.TestCase):
    def test_all_three_booking_fields_required(self):
        result=require_booking_essentials({"brand":"Peugeot","model":"208","energy":"Essence"})
        self.assertEqual(result["brand"],"Peugeot")
        for field in ("brand","model","energy"):
            data={"brand":"Peugeot","model":"208","energy":"Essence"}
            data[field]=" "
            with self.subTest(field=field),self.assertRaisesRegex(
                VehicleCharacteristicsError,"customer_vehicle_booking_essentials_missing"):
                require_booking_essentials(data)

    def test_legacy_optional_normalizer_unchanged(self):
        self.assertEqual(normalize(None),{})
        with self.assertRaises(VehicleCharacteristicsError):
            require_booking_essentials(None)


if __name__=="__main__":
    unittest.main()
