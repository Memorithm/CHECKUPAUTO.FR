"""Offline contract for complete server-side Mercure VL form submission."""
import unittest
from unittest.mock import Mock

from mercure_vl_write_adapter import MercureVlWriteAdapter
from mercure_vl_write_payload import build, MercureVlWritePayloadError


class MercureFullFormHandoffTests(unittest.TestCase):
    def setUp(self):
        self.appointment = {
            "nom": "RECETTE", "prenom": "CHECKUPAUTO",
            "email": "recette@example.invalid", "telephone": "0102030405",
            "marque": "132", "modele": "42", "energie": "2",
            "immatriculation": "AB-123-CD", "date": "2026-10-15T09:00",
        }
        self.metadata = dict(service_id="1763", duration="40", centre_type="1",
                             line_id="454", operator_id="464")

    def test_full_customer_vehicle_and_slot_form(self):
        form = build(appointment=self.appointment, **self.metadata)
        for key, value in self.appointment.items():
            with self.subTest(key=key):
                self.assertEqual(form[key], value)
        for key, value in dict(prestation="1763", ligne_id="454",
                               utilisateur="464", duree="40").items():
            self.assertEqual(form[key], value)

    def test_partial_mercureweb_transfer_is_not_a_booking_form(self):
        partial = {"id": "240", "prestation": "1763"}
        with self.assertRaisesRegex(MercureVlWritePayloadError,
                                    "mercure_vl_customer_payload_incomplete"):
            build(appointment=partial, **self.metadata)

    def test_adapter_submits_full_form_to_administrative_endpoint(self):
        session = Mock()
        session.post.return_value.status_code = 200
        session.post.return_value.json.return_value = {"id": "recette-123"}
        adapter = MercureVlWriteAdapter(
            session=session, base_url="https://mercure.example.invalid",
            metadata=self.metadata, appointment=self.appointment,
            authorized=True, expected_service_label="CONTROLE TECHNIQUE")
        receipt = adapter.create_once(request=Mock())
        self.assertEqual(receipt.provider_reference, "recette-123")
        call = session.post.call_args
        self.assertEqual(call.args[0], "https://mercure.example.invalid/admin/rendez_vous_add")
        self.assertEqual(call.kwargs["data"]["nom"], "RECETTE")
        self.assertEqual(call.kwargs["data"]["immatriculation"], "AB-123-CD")
        self.assertEqual(call.kwargs["data"]["date"], "2026-10-15T09:00")
        self.assertFalse(call.kwargs["allow_redirects"])

    def test_no_unqualified_form_submission(self):
        with self.assertRaises(Exception):
            MercureVlWriteAdapter(
                session=Mock(), base_url="https://mercure.example.invalid",
                metadata=self.metadata, appointment=self.appointment,
                authorized=False)


if __name__ == "__main__":
    unittest.main()
