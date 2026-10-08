import unittest

from customer_vehicle_characteristics import normalize,VehicleCharacteristicsError


class CustomerVehicleCharacteristicsTests(unittest.TestCase):
    def test_valid_vehicle_characteristics(self):
        result=normalize({"brand":"Peugeot","model":"208","energy":"Essence",
                          "vin":"vf3abc12345678901","vehicleType":"VL"})
        self.assertEqual(result["brand"],"Peugeot")
        self.assertEqual(result["vin"],"VF3ABC12345678901")

    def test_legacy_vehicle_without_characteristics(self):
        self.assertEqual(normalize(None),{})

    def test_invalid_values_are_rejected(self):
        for data in ({"brand":123},{"unknown":"x"},{"vin":"INVALID"},
                     {"grossWeightKg":"-1"},{"firstRegistrationDate":"2100-01-01"}):
            with self.subTest(data=data),self.assertRaises(VehicleCharacteristicsError):
                normalize(data)


if __name__=="__main__":
    unittest.main()
