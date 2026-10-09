import unittest
from unittest.mock import Mock
from mercure_booking_write_contract import BookingWriteRequest,MercureBookingWriteError
from mercure_vl_write_adapter import MercureVlWriteAdapter

class Tests(unittest.TestCase):
    def setUp(self):
        self.reader=Mock(return_value=object())
        self.appointment=dict(nom="Test",prenom="Client",email="test@example.invalid",
            telephone="0102030405",marque="132",modele="42",energie="2",
            immatriculation="AB-123-CD",date="2026-10-14T09:00")
        self.metadata=dict(service_id="1763",duration="40",centre_type="1",
                           line_id="454",operator_id="464")
        self.request=BookingWriteRequest("booking-integration-key-001","account1","vehicle1",
                                          "technical","2026-10-14","09:00",8000)
    def adapter(self,reader=None):
        return MercureVlWriteAdapter(session=Mock(),base_url="https://rdv.checkupauto.fr",
            metadata=self.metadata,appointment=self.appointment,authorized=True,
            identity_reader=reader,expected_service_label="CONTROLE TECHNIQUE")
    def test_reader_receives_exact_customer_context(self):
        adapter=self.adapter(self.reader)
        proof=adapter.read_identity(self.request,"123")
        self.assertIsNotNone(proof)
        self.reader.assert_called_once_with(reference="123",date="2026-10-14",
            account_id="account1",vehicle_id="vehicle1",service="technical",
            registration="AB-123-CD",expected_service_label="CONTROLE TECHNIQUE",
            expected_time="09:00")
    def test_reader_missing_fails_closed(self):
        with self.assertRaisesRegex(MercureBookingWriteError,"reader_unqualified"):
            self.adapter().read_identity(self.request,"123")
    def test_wrong_slot_blocks_reader(self):
        bad=BookingWriteRequest("booking-integration-key-001","account1","vehicle1",
                                "technical","2026-10-14","10:20",8000)
        with self.assertRaisesRegex(MercureBookingWriteError,"slot_mismatch"):
            self.adapter(self.reader).read_identity(bad,"123")
        self.reader.assert_not_called()
