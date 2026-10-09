import datetime as dt
import unittest
from unittest.mock import patch

from mercure_booking_write_contract import BookingWriteRequest
import mercure_customer_booking_assembly as assembly


class CustomerBookingAssemblyTests(unittest.TestCase):
    def setUp(self):
        self.request=BookingWriteRequest(
            "customer-booking-assembly-key-001","account-1","vehicle-1","technical",
            (dt.date.today()+dt.timedelta(days=2)).isoformat(),"10:20",8000)
        self.account={"accountId":"account-1","surname":"Test","givenName":"Client",
                      "addressLine1":"1 rue Exemple","postalCode":"75001","city":"Paris",
                      "phone":"0102030405","email":"client@example.invalid"}
        self.vehicle={"vehicleId":"vehicle-1","registration":"AB-123-CD",
                      "characteristics":{"brand":"Peugeot","model":"208","energy":"Essence"}}
        self.mapping={"brandId":"132","modelId":"42","energyId":"2","mappingVerified":True}

    def test_qualified_payload_is_read_only(self):
        with patch.object(assembly,"resolve",return_value=self.mapping) as resolver:
            result=assembly.assemble(request=self.request,account=self.account,vehicle=self.vehicle)
        self.assertEqual(result["appointment"]["immatriculation"],"AB-123-CD")
        self.assertEqual(result["billing"]["surname"],"Test")
        self.assertFalse(result["providerWritePerformed"])
        self.assertFalse(result["bookingConfirmed"])
        resolver.assert_called_once_with(brand="Peugeot",model="208",energy="Essence")

    def test_foreign_vehicle_rejected_before_provider_lookup(self):
        with patch.object(assembly,"resolve") as resolver:
            with self.assertRaisesRegex(assembly.CustomerBookingAssemblyError,"booking_account_vehicle_mismatch"):
                assembly.assemble(request=self.request,account=self.account,vehicle={**self.vehicle,"vehicleId":"foreign"})
            resolver.assert_not_called()

    def test_incomplete_billing_rejected_before_provider_lookup(self):
        with patch.object(assembly,"resolve") as resolver:
            with self.assertRaises(ValueError):
                assembly.assemble(request=self.request,account={**self.account,"surname":""},vehicle=self.vehicle)
            resolver.assert_not_called()

    def test_unverified_mapping_rejected(self):
        with patch.object(assembly,"resolve",return_value={**self.mapping,"mappingVerified":False}):
            with self.assertRaisesRegex(assembly.CustomerBookingAssemblyError,"booking_vehicle_mapping_unverified"):
                assembly.assemble(request=self.request,account=self.account,vehicle=self.vehicle)


if __name__=="__main__":
    unittest.main()
