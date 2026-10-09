"""Synthetic integration checks: no Mercure network or appointment write."""
import datetime as dt
import unittest
from unittest.mock import patch

from mercure_booking_write_contract import BookingWriteRequest
from mercure_booking_write_schema import VL_REQUIRED
import mercure_vl_booking_dry_run as dry
import mercure_customer_booking_assembly as assembly


class VlDryRunIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.request=BookingWriteRequest(
            "synthetic-vl-dry-run-key-00001","account-1","vehicle-1","technical",
            (dt.date.today()+dt.timedelta(days=2)).isoformat(),"10:20",8000)
        self.account={"accountId":"account-1","surname":"Test","givenName":"Client",
                      "addressLine1":"1 rue Exemple","postalCode":"75001","city":"Paris",
                      "phone":"0102030405","email":"client@example.invalid"}
        self.vehicle={"vehicleId":"vehicle-1","registration":"AB-123-CD",
                      "registrationSystem":"siv","formulaNumberPresent":True,
                      "characteristics":{"brand":"Peugeot","model":"208","energy":"Essence"}}

    def test_full_assembly_with_verified_reference_mapping(self):
        mapping={"brandId":"132","modelId":"42","energyId":"2","mappingVerified":True}
        with patch.object(assembly,"resolve",return_value=mapping) as resolver:
            result=dry.prepare(request=self.request,account=self.account,
                               vehicle=self.vehicle,observed_form_fields=VL_REQUIRED)
        self.assertTrue(result["readyForProviderQualification"])
        self.assertFalse(result["customerWriteQualified"])
        self.assertFalse(result["providerWritePerformed"])
        self.assertFalse(result["bookingConfirmed"])
        resolver.assert_called_once()

    def test_missing_document_rejected_before_any_write(self):
        vehicle={**self.vehicle,"formulaNumberPresent":False}
        with patch.object(assembly,"resolve",return_value={
            "brandId":"132","modelId":"42","energyId":"2","mappingVerified":True}):
            with self.assertRaises(ValueError):
                dry.prepare(request=self.request,account=self.account,
                            vehicle=vehicle,observed_form_fields=VL_REQUIRED)

    def test_account_mismatch_rejected_without_reference_lookup(self):
        with patch.object(assembly,"resolve") as resolver:
            with self.assertRaises(ValueError):
                dry.prepare(request=self.request,account={**self.account,"accountId":"other"},
                            vehicle=self.vehicle,observed_form_fields=VL_REQUIRED)
            resolver.assert_not_called()


if __name__=="__main__":
    unittest.main()
