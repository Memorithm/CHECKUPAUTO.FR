import unittest
from customer_booking_payment_state import assess

class Tests(unittest.TestCase):
    def setUp(self):
        self.centre={'service':'technical','providerVerified':True,'paymentMode':'centre','paymentRequired':False}
        self.online={'service':'technical','providerVerified':True,'paymentMode':'online','paymentRequired':True}
    def test_centre_is_due_not_paid(self):
        result=assess(policy=self.centre)
        self.assertFalse(result['paid'])
        self.assertEqual(result['state'],'due_at_centre')
    def test_online_starts_unpaid(self):
        self.assertEqual(assess(policy=self.online)['state'],'awaiting_provider')
    def test_captured_requires_provider_verification(self):
        with self.assertRaises(ValueError):assess(policy=self.online,provider_state='captured')
        self.assertTrue(assess(policy=self.online,provider_state='captured',provider_verified=True)['paid'])
    def test_decline_and_cancel_are_unpaid(self):
        for state in ('declined','cancelled'):
            self.assertFalse(assess(policy=self.online,provider_state=state,provider_verified=True)['paid'])
    def test_centre_cannot_claim_provider_capture(self):
        with self.assertRaises(ValueError):assess(policy=self.centre,provider_state='captured',provider_verified=True)
    def test_malformed_policy_is_rejected(self):
        with self.assertRaises(ValueError):assess(policy={'providerVerified':True,'paymentMode':'centre','paymentRequired':True})
if __name__=='__main__':unittest.main()
