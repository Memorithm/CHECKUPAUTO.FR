import unittest
from unittest.mock import Mock,patch
import customer_booking_create_api as api

class Tests(unittest.TestCase):
    def setUp(self):
        self.payload={"service":"technical","date":"2026-10-14","time":"09:00",
                      "vehicleId":"v1","requestKey":"booking-handoff-key-00001"}
        self.account={"accountId":"a1","vehicles":[{"vehicleId":"v1"}]}
        self.context=dict(metadata={},observed_metadata={},service_label="CT",
                          payment_policy={"service":"technical","providerVerified":True,"paymentRequired":True,"paymentMode":"online"},payment_evidence={"providerVerified":True,"paid":True},slot_evidence={"observed":True})
        self.ready={"bookingEnabled":True}

    def test_default_does_not_execute(self):
        with patch.object(api.customer_booking_api,"preflight",return_value=self.ready),patch.object(
            api.in_site_booking_readiness,"public_status",return_value=self.ready):
            with self.assertRaisesRegex(api.BookingCreateUnavailable,"writer_not_connected"):
                api.create(self.payload,account=self.account)

    def test_foreign_vehicle_never_executes(self):
        executor=Mock()
        with patch.object(api.customer_booking_api,"preflight",return_value=self.ready),patch.object(
            api.in_site_booking_readiness,"public_status",return_value=self.ready):
            with self.assertRaises(api.BookingCreateInvalid):
                api.create(self.payload,account={"accountId":"a1","vehicles":[]},
                           executor=executor,trusted_context=self.context)
        executor.assert_not_called()

    def test_injected_executor_receives_owned_vehicle(self):
        executor=Mock(return_value={"confirmed":True})
        with patch.object(api.customer_booking_api,"preflight",return_value=self.ready),patch.object(
            api.in_site_booking_readiness,"public_status",return_value=self.ready):
            result=api.create(self.payload,account=self.account,
                              executor=executor,trusted_context=self.context)
        self.assertTrue(result["confirmed"])
        self.assertEqual(executor.call_args.kwargs["vehicle"]["vehicleId"],"v1")
