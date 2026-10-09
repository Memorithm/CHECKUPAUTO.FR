import unittest
from mercure_vl_appointment_row_identity import verify,MercureAppointmentRowError

class Tests(unittest.TestCase):
    def setUp(self):
        self.kw=dict(reference="123",account_id="account1",vehicle_id="vehicle1",
                     service="technical",registration="AB-123-CD",
                     expected_service_label="CONTROLE TECHNIQUE")
        self.row={"id":123,"immat":"AB-123-CD","prestation":"CONTROLE TECHNIQUE"}

    def test_observed_schema_maps_identity(self):
        self.assertTrue(verify(row=self.row,**self.kw).provider_read_verified)

    def test_wrong_plate_fails(self):
        with self.assertRaises(ValueError):
            verify(row={**self.row,"immat":"ZZ-999-ZZ"},**self.kw)

    def test_wrong_service_fails(self):
        with self.assertRaises(MercureAppointmentRowError):
            verify(row={**self.row,"prestation":"CONTRE VISITE"},**self.kw)
