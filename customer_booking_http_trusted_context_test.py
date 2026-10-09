import unittest
from unittest.mock import patch
import customer_booking_http_trusted_context as context

class Tests(unittest.TestCase):
    def test_unqualified_server_does_not_contact_provider(self):
        with patch.object(context.customer_booking_trusted_route_context,"build") as build:
            with self.assertRaisesRegex(context.BookingHttpContextError,"not_qualified"):
                context.prepare(service="technical",server_config={
                    "enabled":False,"lineId":"","operatorId":""},
                    payment_policy={},payment_evidence=None)
            build.assert_not_called()

    def test_trusted_server_returns_executor_and_context(self):
        qualified=dict(metadata={},observed_metadata={},service_label="CT",
                       payment_policy={},payment_evidence=None)
        with patch.object(context.customer_booking_trusted_route_context,"build",
                          return_value=qualified):
            executor,result=context.prepare(service="technical",server_config={
                "enabled":True,"lineId":"454","operatorId":"464"},
                payment_policy={},payment_evidence=None)
        self.assertIs(executor,context.customer_booking_trusted_executor.execute)
        self.assertEqual(result,qualified)

if __name__=="__main__":
    unittest.main()
