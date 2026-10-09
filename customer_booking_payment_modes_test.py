import unittest
from mercure_vl_payment_policy_source import qualify, MercurePaymentPolicyError
from customer_booking_payment_policy import authorize, BookingPaymentPolicyError

class Tests(unittest.TestCase):
    def test_centre_only_requires_no_prepaid_receipt(self):
        policy=qualify(service='technical',response={'paiementCentre':True,'paiementWeb':False})
        self.assertEqual(policy['paymentMode'],'centre')
        self.assertFalse(policy['paymentRequired'])
        result=authorize(service='technical',policy=policy)
        self.assertTrue(result['authorized'])
        self.assertFalse(result['paid'])
        self.assertEqual(result['paymentMode'],'centre')
    def test_online_requires_verified_payment(self):
        policy=qualify(service='technical',response={'paiementCentre':True,'paiementWeb':True})
        self.assertEqual(policy['paymentMode'],'online')
        with self.assertRaisesRegex(BookingPaymentPolicyError,'evidence_missing'):
            authorize(service='technical',policy=policy)
        result=authorize(service='technical',policy=policy,payment_evidence={'providerVerified':True,'paid':True})
        self.assertTrue(result['paid'])
    def test_no_payment_option_fails_closed(self):
        with self.assertRaisesRegex(MercurePaymentPolicyError,'no_payment_mode'):
            qualify(service='technical',response={'paiementCentre':False,'paiementWeb':False})
    def test_false_receipt_cannot_be_passed_as_centre_payment(self):
        policy=qualify(service='technical',response={'paiementCentre':True,'paiementWeb':False})
        with self.assertRaisesRegex(BookingPaymentPolicyError,'cannot_be_prepaid'):
            authorize(service='technical',policy=policy,payment_evidence={'paid':True,'providerVerified':True})
    def test_inconsistent_mode_policy_is_rejected(self):
        with self.assertRaisesRegex(BookingPaymentPolicyError,'mode_invalid'):
            authorize(service='technical',policy={'service':'technical','providerVerified':True,'paymentRequired':False,'paymentMode':'online'})
if __name__=='__main__': unittest.main()
