import unittest
from unittest.mock import patch
import customer_booking_payment_sandbox_status as status

class Tests(unittest.TestCase):
    def setUp(self):
        self.kw={'account_id':'a1','request_key':'booking-key-000000000001','expected_amount_cents':8000}
        self.online={'providerVerified':True,'paymentMode':'online','paymentRequired':True}
        self.centre={'providerVerified':True,'paymentMode':'centre','paymentRequired':False}
        self.booking={'booking':{'confirmed':True},'payment':{'state':'awaiting_provider','paid':False}}
    def test_centre_never_queries_bank(self):
        with patch.object(status.verified,'read') as reader,patch.object(status.bridge,'view',return_value=self.booking) as bridge:
            result=status.view(**self.kw,payment_policy=self.centre)
        reader.assert_not_called()
        self.assertEqual(result['environment'],'provider-centre')
        bridge.assert_called_once()
    def test_captured_sandbox_requires_verified_evidence(self):
        with patch.object(status.verified,'read',return_value={'state':'captured','paid':True,'providerVerified':True,'bookingPaymentBound':True}),patch.object(status.bridge,'view',return_value=self.booking) as bridge:
            result=status.view(**self.kw,payment_policy=self.online)
        self.assertEqual(result['environment'],'sandbox')
        self.assertEqual(bridge.call_args.kwargs['provider_state'],'captured')
    def test_unverified_capture_fails_closed(self):
        with patch.object(status.verified,'read',return_value={'state':'captured','paid':True,'providerVerified':False,'bookingPaymentBound':True}),patch.object(status.bridge,'view') as bridge:
            with self.assertRaisesRegex(ValueError,'capture_unverified'):status.view(**self.kw,payment_policy=self.online)
        bridge.assert_not_called()
    def test_pending_is_not_paid(self):
        with patch.object(status.verified,'read',return_value={'state':'pending','paid':False,'providerVerified':False,'bookingPaymentBound':True}),patch.object(status.bridge,'view',return_value=self.booking):
            result=status.view(**self.kw,payment_policy=self.online)
        self.assertFalse(result['payment']['paid'])
        self.assertEqual(result['payment']['providerState'],'pending')
    def test_unverified_policy_never_reads_payment(self):
        with patch.object(status.verified,'read') as reader:
            with self.assertRaises(ValueError):status.view(**self.kw,payment_policy={})
        reader.assert_not_called()
if __name__=='__main__':unittest.main()
