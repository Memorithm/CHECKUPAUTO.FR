import unittest
from unittest.mock import patch
import customer_booking_trusted_route_context as context

class Tests(unittest.TestCase):
    def test_disabled_config_never_fetches_provider(self):
        with patch.object(context.mercure_vl_provider_metadata_resolver,"resolve") as resolver:
            with self.assertRaises(context.BookingRouteContextError):
                context.build(service="technical",server_config={
                    "lineId":"454","operatorId":"464","enabled":False},
                    payment_policy={},payment_evidence=None)
            resolver.assert_not_called()

    def test_verified_provider_context(self):
        resolved={"metadata":{"service_id":"1763"},"observed_metadata":{},
                  "service_label":"CONTROLE TECHNIQUE"}
        with patch.object(context.mercure_vl_provider_metadata_resolver,"resolve",
                          return_value=resolved) as resolver:
            result=context.build(service="technical",server_config={
                "lineId":"454","operatorId":"464","enabled":True},
                payment_policy={"providerVerified":True},payment_evidence=None)
        self.assertEqual(result["metadata"],resolved["metadata"])
        resolver.assert_called_once()
