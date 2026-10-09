import unittest
from mercure_vl_provider_identity_reader import verify_record,ProviderIdentityUnavailable

class Tests(unittest.TestCase):
    def setUp(self):
        self.kw=dict(provider_reference="ref1",account_id="a1",vehicle_id="v1",
                     service="technical",registration="AB-123-CD",expected_provider_service="1763")
        self.record={"id":"ref1","immatriculation":"AB-123-CD",
                     "prestation_id":"1763","independentRead":True}

    def test_exact_record(self):
        self.assertTrue(verify_record(record=self.record,**self.kw).provider_read_verified)

    def test_mismatched_plate(self):
        with self.assertRaises(ProviderIdentityUnavailable):
            verify_record(record={**self.record,"immatriculation":"ZZ-999-ZZ"},**self.kw)

    def test_mismatched_service(self):
        with self.assertRaises(ProviderIdentityUnavailable):
            verify_record(record={**self.record,"prestation_id":"1771"},**self.kw)

    def test_unverified_read(self):
        with self.assertRaises(ProviderIdentityUnavailable):
            verify_record(record={**self.record,"independentRead":False},**self.kw)
