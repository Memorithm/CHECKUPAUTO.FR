import unittest
from unittest.mock import Mock
from mercure_booking_write_contract import MercureBookingWriteError
from mercure_vl_write_adapter import MercureVlWriteAdapter

class Tests(unittest.TestCase):
    def setUp(self):
        self.session=Mock()
        self.metadata=dict(service_id="1763",duration="40",centre_type="1",
                           line_id="454",operator_id="464")
        self.appointment=dict(nom="Test",prenom="Client",email="test@example.invalid",
            telephone="0102030405",marque="132",modele="42",energie="2",
            immatriculation="AB-123-CD",date="2026-10-14T09:00")

    def adapter(self,authorized=True):
        return MercureVlWriteAdapter(session=self.session,base_url="https://rdv.checkupauto.fr",
            metadata=self.metadata,appointment=self.appointment,authorized=authorized)

    def test_default_refuses_write(self):
        with self.assertRaises(MercureBookingWriteError):
            self.adapter(authorized=False)
        self.session.post.assert_not_called()

    def test_provider_receipt(self):
        self.session.post.return_value.status_code=200
        self.session.post.return_value.json.return_value={"id":"123"}
        adapter=self.adapter()
        self.assertEqual(adapter.create_once(None).provider_reference,"123")
        self.assertEqual(self.session.post.call_count,1)

    def test_timeout_never_retries(self):
        self.session.post.side_effect=TimeoutError("uncertain")
        adapter=self.adapter()
        with self.assertRaises(MercureBookingWriteError):
            adapter.create_once(None)
        with self.assertRaisesRegex(MercureBookingWriteError,"already_attempted"):
            adapter.create_once(None)
        self.assertEqual(self.session.post.call_count,1)
