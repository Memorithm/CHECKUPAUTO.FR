import unittest
from unittest.mock import patch
import customer_booking_http_trusted_composition as composition

class Tests(unittest.TestCase):
    def setUp(self):
        self.payload={"service":"technical"}

    def test_disabled_server_blocks_before_payment(self):
        payment_calls=[]
        with self.assertRaises(composition.BookingHttpCompositionUnavailable):
            composition.compose(payload=self.payload,
                server_config_loader=lambda:{"enabled":False},
                payment_policy_loader=lambda service:payment_calls.append(service),
                payment_evidence_loader=lambda service:None)
        self.assertEqual(payment_calls,[])

    def test_qualified_server_injects_trusted_executor(self):
        trusted={"metadata":{},"observed_metadata":{},"service_label":"CT",
                 "payment_policy":{},"payment_evidence":None}
        with patch.object(composition.customer_booking_trusted_route_context,"build",
                          return_value=trusted):
            executor,context=composition.compose(payload=self.payload,
                server_config_loader=lambda:{"enabled":True},
                payment_policy_loader=lambda service:{"service":service},
                payment_evidence_loader=lambda service:None)
        self.assertIs(executor,composition.customer_booking_trusted_executor.execute)
        self.assertEqual(context,trusted)

    def test_browser_cannot_supply_provider_context(self):
        with self.assertRaises(composition.BookingHttpCompositionUnavailable):
            composition.compose(payload={"service":"technical","metadata":{"line_id":"1"}},
                server_config_loader=lambda:{"enabled":False},
                payment_policy_loader=lambda service:None,
                payment_evidence_loader=lambda service:None)
