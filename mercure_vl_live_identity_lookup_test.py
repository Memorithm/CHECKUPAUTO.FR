import unittest
from unittest.mock import patch
import mercure_vl_live_identity_lookup as lookup

class Tests(unittest.TestCase):
    def setUp(self):
        self.kw=dict(reference="123",date="2026-10-14",account_id="a",
                     vehicle_id="v",service="technical",registration="AB-123-CD",
                     expected_service_label="CONTROLE TECHNIQUE",expected_time="09:00")
        self.row={"id":123,"immat":"AB-123-CD","prestation":"CONTROLE TECHNIQUE","date_rdv":"2026-10-14T09:00:00"}

    def test_live_reader_binds_provider_record(self):
        with patch.object(lookup.mercure,"_session",return_value=object()),patch.object(
            lookup.mercure,"_appointments",return_value=[self.row]):
            result=lookup.read_and_verify(**self.kw)
        self.assertTrue(result.provider_read_verified)

    def test_missing_reference_fails(self):
        with patch.object(lookup.mercure,"_session",return_value=object()),patch.object(
            lookup.mercure,"_appointments",return_value=[]):
            with self.assertRaises(lookup.MercureVlLiveIdentityError):
                lookup.read_and_verify(**self.kw)

    def test_wrong_vehicle_fails(self):
        with patch.object(lookup.mercure,"_session",return_value=object()),patch.object(
            lookup.mercure,"_appointments",return_value=[{**self.row,"immat":"ZZ-999-ZZ"}]):
            with self.assertRaises(ValueError):
                lookup.read_and_verify(**self.kw)
