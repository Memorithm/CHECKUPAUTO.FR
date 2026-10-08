import datetime as dt
import unittest
from dataclasses import replace

from mercure_booking_write_contract import BookingWriteRequest
from mercure_customer_payload_contract import QualifiedCustomerDetails, CustomerPayloadNotQualified, qualify


class CustomerPayloadQualificationTests(unittest.TestCase):
    def setUp(self):
        self.request=BookingWriteRequest(
            request_key="customer-mercure-booking-key-001",
            account_id="customer-1",vehicle_id="vehicle-1",service="technical",
            date=(dt.date.today()+dt.timedelta(days=1)).isoformat(),
            time="10:20",price_cents=8000)
        self.details=QualifiedCustomerDetails(
            account_id="customer-1",vehicle_id="vehicle-1",registration="AB-123-CD",
            surname="TEST",given_name="TEST",email="test@example.invalid",
            telephone="0100000000",provider_brand_id="132",provider_model_id="1",
            provider_energy_id="2",mapping_verified=True)

    def test_explicitly_qualified_customer_payload(self):
        result=qualify(self.request,self.details)
        self.assertEqual(result["immatriculation"],"AB-123-CD")
        self.assertEqual(result["marque"],"132")
        self.assertEqual(result["date"],self.request.date+"T10:20")

    def test_unverified_mapping_cannot_be_used(self):
        with self.assertRaisesRegex(CustomerPayloadNotQualified,"mercure_vehicle_mapping_unverified"):
            qualify(self.request,replace(self.details,mapping_verified=False))

    def test_account_and_vehicle_mismatch_rejected(self):
        for field in ("account_id","vehicle_id"):
            with self.subTest(field=field),self.assertRaisesRegex(CustomerPayloadNotQualified,"mercure_customer_vehicle_mismatch"):
                qualify(self.request,replace(self.details,**{field:"other"}))

    def test_invalid_registration_and_provider_ids_rejected(self):
        for field,value in (("registration","AB123CD"),("provider_brand_id","unknown"),
                            ("provider_model_id",""),("provider_energy_id","2;DROP")):
            with self.subTest(field=field),self.assertRaises(CustomerPayloadNotQualified):
                qualify(self.request,replace(self.details,**{field:value}))


if __name__=="__main__":
    unittest.main()
