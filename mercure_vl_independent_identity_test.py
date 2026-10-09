import unittest
from mercure_vl_independent_identity import verify

class Tests(unittest.TestCase):
    def setUp(self):
        self.kw=dict(reference="provider1",account_id="account1",
                     vehicle_id="vehicle1",service="technical")
        self.record=dict(reference="provider1",accountId="account1",
                         vehicleId="vehicle1",service="technical",independentlyRead=True)

    def test_verified_record(self):
        self.assertTrue(verify(record=self.record,**self.kw).provider_read_verified)

    def test_foreign_vehicle_rejected(self):
        with self.assertRaises(ValueError):
            verify(record={**self.record,"vehicleId":"other"},**self.kw)

    def test_receipt_not_independent(self):
        with self.assertRaises(ValueError):
            verify(record={**self.record,"independentlyRead":False},**self.kw)
