import unittest
import inspect
import customer_http


class CustomerVehicleReferenceApiContractTests(unittest.TestCase):
    def test_reference_route_requires_customer_authentication(self):
        source=inspect.getsource(customer_http.handle)
        self.assertIn("if path==VEHICLE_REFERENCES_ROUTE:",source)
        self.assertIn('customer_auth_required',source)
        self.assertIn('mercure_brand_energy_reference.fetch_references()',source)
        self.assertIn('mercure_vehicle_reference.models(centre_type="1",brand_id=brand_id[0])',source)

    def test_reference_route_is_get_only_and_fails_closed(self):
        source=inspect.getsource(customer_http.handle)
        segment=source.split("if path==VEHICLE_REFERENCES_ROUTE:",1)[1].split('if path=="/api/customer/booking/preflight":',1)[0]
        self.assertIn('if command!="GET":',segment)
        self.assertIn('vehicle_reference_unavailable',segment)
        self.assertNotIn('.post(',segment)
        self.assertNotIn('create_appointment(',segment)


if __name__=="__main__":
    unittest.main()
