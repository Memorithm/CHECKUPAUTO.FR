import unittest
from unittest.mock import Mock,patch
import customer_booking_create_api as api

class Tests(unittest.TestCase):
    def test_qualified_route_passes_explicit_server_authorization(self):
        payload={"service":"technical","date":"2026-10-14","time":"09:00",
                 "vehicleId":"v1","requestKey":"booking-route-key-0000001"}
        account={"accountId":"a1","vehicles":[{"vehicleId":"v1"}]}
        trusted=dict(metadata={},observed_metadata={},service_label="CT",
                     payment_policy={},payment_evidence=None)
        executor=Mock(return_value={"confirmed":True})
        ready={"bookingEnabled":True}
        with patch.object(api.customer_booking_api,"preflight",return_value=ready),patch.object(
            api.in_site_booking_readiness,"public_status",return_value=ready):
            result=api.create(payload,account=account,executor=executor,trusted_context=trusted)
        self.assertTrue(result["confirmed"])
        self.assertIs(executor.call_args.kwargs["server_authorized"],True)
