import unittest
from unittest.mock import patch
import customer_booking_trusted_executor as module

class Tests(unittest.TestCase):
    def setUp(self):
        self.kw=dict(payload={"service":"technical"},account={},vehicle={},
            metadata={"service_id":"1763","duration":"40","centre_type":"1",
                      "line_id":"454","operator_id":"464"},
            observed_metadata={},service_label="TOUT VEHICULE HORS CAMPING CAR",
            payment_policy={},payment_evidence=None,slot_evidence={"observed":True})

    def test_denied_by_default(self):
        with patch.object(module.customer_booking_server_composition,"execute") as delegate:
            with self.assertRaises(module.TrustedBookingContextError):
                module.execute(**self.kw)
            delegate.assert_not_called()

    def test_missing_metadata_denied(self):
        with patch.object(module.customer_booking_server_composition,"execute") as delegate:
            with self.assertRaises(module.TrustedBookingContextError):
                module.execute(**{**self.kw,"metadata":{}},server_authorized=True)
            delegate.assert_not_called()

    def test_authorized_delegation(self):
        with patch.object(module.customer_booking_server_composition,"execute",
                          return_value={"confirmed":False}) as delegate:
            result=module.execute(**self.kw,server_authorized=True)
        self.assertFalse(result["confirmed"])
        self.assertTrue(delegate.call_args.kwargs["authorized"])
        self.assertEqual(delegate.call_args.kwargs["line_id"],"454")

if __name__=="__main__":
    unittest.main()
