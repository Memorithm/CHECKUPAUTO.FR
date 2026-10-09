import unittest
import datetime as dt
from unittest.mock import patch
import customer_booking_server_execution as executor

class Tests(unittest.TestCase):
    def setUp(self):
        self.payload=dict(service="technical",date="2026-10-14",time="09:00",
                          vehicleId="vehicle1",requestKey="booking-server-key-00001")
        self.kw=dict(payload=self.payload,account={"accountId":"account1"},
                     vehicle={"vehicleId":"vehicle1"},metadata={},observed_metadata={},
                     service_label="CONTROLE TECHNIQUE")

        self.kw["metadata"] = {"line_id":"454","service_id":"1763","duration":"40"}
        self.kw["slot_evidence"] = {"service":"technical","date":self.payload["date"],
            "time":self.payload["time"],"lineId":"454","serviceId":"1763","duration":"40",
            "centreType":"1","observed":True,"slotAvailable":True,"slotHeld":False,
            "priceCents":8000,"source":"mercure-single-vl-resource-and-live-availability",
            "checkedAt":dt.datetime.now(dt.timezone.utc).isoformat()}

    def test_no_server_authorization(self):
        with patch.object(executor.mercure_vl_booking_coordinator,"create_and_verify") as writer:
            with self.assertRaises(executor.CustomerBookingExecutionError):
                executor.execute(**self.kw)
            writer.assert_not_called()

    def test_foreign_vehicle(self):
        with patch.object(executor.customer_booking_api,"preflight") as preflight:
            with self.assertRaisesRegex(executor.CustomerBookingExecutionError,"vehicle_mismatch"):
                executor.execute(**{**self.kw,"vehicle":{"vehicleId":"foreign"}},server_authorized=True)
            preflight.assert_not_called()

    def test_validated_request_reaches_coordinator(self):
        result=dict(service="technical",date="2026-10-14",time="09:00",
                    vehicleId="vehicle1",priceCents=8000,bookingEnabled=True)
        with patch.object(executor.customer_booking_api,"preflight",return_value=result),patch.object(
            executor.mercure_vl_booking_coordinator,"create_and_verify",
            return_value={"confirmed":True}) as coordinator:
            output=executor.execute(**self.kw,server_authorized=True, 
                payment_authorizer=lambda **kwargs: {"authorized":True})
        self.assertTrue(output["confirmed"])
        self.assertEqual(coordinator.call_args.kwargs["request"].account_id,"account1")
