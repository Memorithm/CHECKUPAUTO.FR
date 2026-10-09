import unittest
import datetime as dt
from unittest.mock import Mock,patch
import customer_booking_server_execution as execution

class Tests(unittest.TestCase):
    def setUp(self):
        self.payload=dict(service="technical",date="2026-10-14",time="09:00",
                          vehicleId="v1",requestKey="booking-payment-key-000001")
        self.kw=dict(payload=self.payload,account={"accountId":"a1"},
                     vehicle={"vehicleId":"v1"},metadata={},observed_metadata={},
                     service_label="CONTROLE TECHNIQUE",server_authorized=True)
        self.preflight=dict(bookingEnabled=True,service="technical",
                            date="2026-10-14",time="09:00",priceCents=8000)

        self.kw["metadata"] = {"line_id":"454","service_id":"1763","duration":"40"}
        self.kw["slot_evidence"] = {"service":"technical","date":self.payload["date"],
            "time":self.payload["time"],"lineId":"454","serviceId":"1763","duration":"40",
            "centreType":"1","observed":True,"slotAvailable":True,"slotHeld":False,
            "priceCents":8000,"source":"mercure-single-vl-resource-and-live-availability",
            "checkedAt":dt.datetime.now(dt.timezone.utc).isoformat()}

    def test_missing_policy_authorizer_blocks_write(self):
        with patch.object(execution.customer_booking_api,"preflight",return_value=self.preflight),patch.object(
            execution.mercure_vl_booking_coordinator,"create_and_verify") as writer:
            with self.assertRaisesRegex(execution.CustomerBookingExecutionError,"payment_policy_unqualified"):
                execution.execute(**self.kw)
            writer.assert_not_called()

    def test_rejected_policy_blocks_write(self):
        deny=Mock(side_effect=ValueError("payment_unverified"))
        with patch.object(execution.customer_booking_api,"preflight",return_value=self.preflight),patch.object(
            execution.mercure_vl_booking_coordinator,"create_and_verify") as writer:
            with self.assertRaisesRegex(ValueError,"payment_unverified"):
                execution.execute(**self.kw,payment_authorizer=deny)
            writer.assert_not_called()

    def test_authorized_policy_precedes_write(self):
        authorize=Mock(return_value={"authorized":True})
        with patch.object(execution.customer_booking_api,"preflight",return_value=self.preflight),patch.object(
            execution.mercure_vl_booking_coordinator,"create_and_verify",return_value={"confirmed":True}) as writer:
            result=execution.execute(**self.kw,payment_authorizer=authorize,payment_policy={"service":"technical"})
        self.assertTrue(result["confirmed"])
        authorize.assert_called_once()
        writer.assert_called_once()
