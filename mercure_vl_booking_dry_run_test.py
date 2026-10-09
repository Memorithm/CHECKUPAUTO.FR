import datetime as dt
import unittest
from unittest.mock import patch

import mercure_vl_booking_dry_run as dry
from mercure_booking_write_contract import BookingWriteRequest
from mercure_booking_write_schema import VL_REQUIRED


class MercureVlBookingDryRunTests(unittest.TestCase):
    def setUp(self):
        self.request=BookingWriteRequest(
            "mercure-vl-dry-run-key-00001","account-1","vehicle-1","technical",
            (dt.date.today()+dt.timedelta(days=2)).isoformat(),"10:20",8000)
        self.account={"accountId":"account-1"}
        self.vehicle={"vehicleId":"vehicle-1"}
        self.assembled={"appointment":{key:"qualified" for key in (
            "nom","prenom","email","telephone","marque","modele","energie",
            "immatriculation","date")},"providerWritePerformed":False}

    def test_qualified_dry_run_does_not_enable_writes(self):
        with patch.object(dry,"assemble",return_value=self.assembled) as assemble:
            result=dry.prepare(request=self.request,account=self.account,
                               vehicle=self.vehicle,observed_form_fields=VL_REQUIRED)
        self.assertTrue(result["readyForProviderQualification"])
        self.assertFalse(result["customerWriteQualified"])
        self.assertFalse(result["providerWritePerformed"])
        self.assertFalse(result["bookingConfirmed"])
        assemble.assert_called_once()

    def test_missing_schema_blocks_before_customer_assembly(self):
        with patch.object(dry,"assemble") as assemble:
            with self.assertRaisesRegex(dry.MercureVlDryRunError,"mercure_vl_form_schema_incomplete"):
                dry.prepare(request=self.request,account=self.account,
                            vehicle=self.vehicle,observed_form_fields=VL_REQUIRED-{"prestation"})
            assemble.assert_not_called()

    def test_heavy_vehicle_fields_are_not_accepted_as_vl(self):
        with patch.object(dry,"assemble") as assemble:
            with self.assertRaises(dry.MercureVlDryRunError):
                dry.prepare(request=self.request,account=self.account,vehicle=self.vehicle,
                            observed_form_fields={"nom_pl","prestation_pl","date"})
            assemble.assert_not_called()


if __name__=="__main__":
    unittest.main()
