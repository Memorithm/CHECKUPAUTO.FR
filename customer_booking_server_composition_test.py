import unittest
from unittest.mock import patch
import customer_booking_server_composition as composition

class Tests(unittest.TestCase):
    def setUp(self):
        self.kw=dict(payload={"service":"technical"},account={},vehicle={},
                     line_id="454",operator_id="464",payment_policy={},
                     payment_evidence=None,slot_evidence={"observed":True})

    def test_default_blocks_before_provider_lookup(self):
        with patch.object(composition.mercure_vl_provider_metadata_resolver,"resolve") as resolver:
            with self.assertRaises(composition.CustomerBookingCompositionError):
                composition.execute(**self.kw)
            resolver.assert_not_called()

    def test_trusted_server_composes_payment_and_provider(self):
        provider=dict(metadata={},observed_metadata={},service_label="CT",
                      slot_evidence={"observed":True})
        with patch.object(composition.mercure_vl_provider_metadata_resolver,"resolve",
                          return_value=provider),patch.object(
            composition.customer_booking_server_execution,"execute",
            return_value={"confirmed":True}) as executor:
            result=composition.execute(**self.kw,authorized=True)
        self.assertTrue(result["confirmed"])
        self.assertIs(executor.call_args.kwargs["payment_authorizer"],
                      composition.customer_booking_payment_policy.authorize)
