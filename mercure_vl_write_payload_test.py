import unittest

from mercure_vl_write_payload import build,MercureVlWritePayloadError


class MercureVlWritePayloadTests(unittest.TestCase):
    def setUp(self):
        self.appointment={"nom":"Test","prenom":"Client","email":"client@example.invalid",
            "telephone":"0102030405","marque":"132","modele":"42","energie":"2",
            "immatriculation":"AB-123-CD","date":"2026-10-14T09:00"}
        self.metadata={"service_id":"55","duration":"40","centre_type":"1",
                       "line_id":"454","operator_id":"464"}

    def test_complete_payload(self):
        payload=build(appointment=self.appointment,**self.metadata)
        self.assertEqual(payload["immatriculation"],"AB-123-CD")
        self.assertEqual(payload["prestation"],"55")
        self.assertEqual(payload["rendezvous_id"],"")

    def test_missing_provider_metadata_fails(self):
        for field in self.metadata:
            with self.subTest(field=field),self.assertRaises(MercureVlWritePayloadError):
                build(appointment=self.appointment,**{**self.metadata,field:""})

    def test_invalid_customer_payload_fails(self):
        with self.assertRaisesRegex(MercureVlWritePayloadError,"mercure_vl_customer_payload_incomplete"):
            build(appointment={**self.appointment,"immatriculation":""},**self.metadata)

    def test_heavy_centre_type_rejected(self):
        with self.assertRaisesRegex(MercureVlWritePayloadError,"mercure_vl_centre_type_invalid"):
            build(appointment=self.appointment,**{**self.metadata,"centre_type":"2"})


if __name__=="__main__":
    unittest.main()
