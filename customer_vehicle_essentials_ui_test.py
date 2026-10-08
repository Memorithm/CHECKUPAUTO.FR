import unittest
import customer_http


class VehicleEssentialUiTests(unittest.TestCase):
    def test_customer_dashboard_contains_required_and_optional_vehicle_fields(self):
        import inspect
        source=inspect.getsource(customer_http)
        for field in ("vehicleBrand","vehicleModel","vehicleEnergy"):
            self.assertIn('id="'+field+'"',source)
        self.assertIn('Informations complémentaires (facultatives)',source)
        self.assertIn('characteristics:getVehicleCharacteristics()',source)
        self.assertIn('fillVehicleCharacteristics(row.characteristics)',source)

    def test_registration_specific_fields_remain(self):
        import inspect
        source=inspect.getsource(customer_http)
        self.assertIn('vehicleFormulaNumber',source)
        self.assertIn('vehicleCardIssueDate',source)


if __name__=="__main__":
    unittest.main()
