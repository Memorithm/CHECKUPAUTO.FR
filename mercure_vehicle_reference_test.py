import unittest
from unittest.mock import patch

import mercure_vehicle_reference as lookup


class Response:
    def __init__(self,records):
        self.records=records
    def raise_for_status(self):
        pass
    def json(self):
        return self.records


class MercureVehicleReferenceTests(unittest.TestCase):
    def test_provider_model_reference_is_read_only(self):
        session=unittest.mock.Mock()
        session.get.return_value=Response([{"id":123,"libele":"Model A"}])
        with patch.object(lookup.mercure,"_session",return_value=session), \
             patch.object(lookup.mercure,"_check_auth",side_effect=lambda x:x):
            result=lookup.models(centre_type="1",brand_id="132")
        self.assertEqual(result,[{"id":"123","label":"Model A"}])
        self.assertEqual(session.get.call_count,1)
        self.assertIn("/admin/modeles/1/132",session.get.call_args.args[0])

    def test_invalid_reference_id_fails_before_network(self):
        with patch.object(lookup.mercure,"_session") as session:
            with self.assertRaisesRegex(lookup.MercureReferenceError,"mercure_reference_id_invalid"):
                lookup.models(centre_type="1",brand_id="../132")
            session.assert_not_called()

    def test_malformed_provider_response_fails_closed(self):
        session=unittest.mock.Mock()
        session.get.return_value=Response([{"id":"bad","libele":"Model"}])
        with patch.object(lookup.mercure,"_session",return_value=session), \
             patch.object(lookup.mercure,"_check_auth",side_effect=lambda x:x):
            with self.assertRaisesRegex(lookup.MercureReferenceError,"mercure_reference_invalid"):
                lookup.models(centre_type="1",brand_id="132")


if __name__=="__main__":
    unittest.main()
