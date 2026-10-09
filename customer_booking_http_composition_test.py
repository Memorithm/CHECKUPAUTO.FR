import unittest
from unittest.mock import patch
import customer_booking_http_composition as composition

class Tests(unittest.TestCase):
    def test_disabled_context_never_returns_writer(self):
        with patch.object(composition.customer_booking_trusted_route_context,"build",
                          side_effect=ValueError("disabled")):
            with self.assertRaises(composition.BookingHttpCompositionError):
                composition.prepare(service="technical",server_config={
                    "lineId":"","operatorId":"","enabled":False},
                    payment_policy={},payment_evidence=None)

    def test_verified_context_returns_trusted_executor(self):
        context={"metadata":{},"observed_metadata":{},"service_label":"CT",
                 "payment_policy":{},"payment_evidence":None}
        with patch.object(composition.customer_booking_trusted_route_context,"build",
                          return_value=context):
            executor,result=composition.prepare(service="technical",server_config={
                "lineId":"454","operatorId":"464","enabled":True},
                payment_policy={},payment_evidence=None)
        self.assertIs(executor,composition.customer_booking_trusted_executor.execute)
        self.assertIs(result,context)

if __name__=="__main__":
    unittest.main()
