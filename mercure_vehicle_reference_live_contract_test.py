"""Reference lookup is read-only and does not establish a customer mapping."""
import unittest
from unittest.mock import patch

import mercure_vehicle_reference as refs
from mercure_customer_payload_contract import (
    QualifiedCustomerDetails, CustomerPayloadNotQualified, qualify,
)
from mercure_booking_write_contract import BookingWriteRequest
import datetime as dt


class Response:
    def raise_for_status(self):
        pass
    def json(self):
        return [{"id":1350,"libele":"Provider model"}]


class MercureVehicleReferenceContractTest(unittest.TestCase):
    def test_provider_reference_does_not_automatically_qualify_customer(self):
        session=unittest.mock.Mock()
        session.get.return_value=Response()
        with patch.object(refs.mercure,"_session",return_value=session), \
             patch.object(refs.mercure,"_check_auth",side_effect=lambda r:r):
            models=refs.models(centre_type="1",brand_id="132")
        self.assertEqual(models[0]["id"],"1350")
        request=BookingWriteRequest("idempotency-booking-key-0001","customer-1","vehicle-1",
                                    "technical",(dt.date.today()+dt.timedelta(days=1)).isoformat(),
                                    "10:20",8000)
        details=QualifiedCustomerDetails("customer-1","vehicle-1","AB-123-CD",
            "TEST","TEST","test@example.invalid","0100000000",
            "132",models[0]["id"],"2",False)
        with self.assertRaisesRegex(CustomerPayloadNotQualified,"mercure_vehicle_mapping_unverified"):
            qualify(request,details)


if __name__=="__main__":
    unittest.main()
