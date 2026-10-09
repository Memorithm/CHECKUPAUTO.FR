import unittest
from unittest.mock import patch
import customer_booking_payment_status_bridge as bridge

class Tests(unittest.TestCase):
    def setUp(self):
        self.booking={'ok':True,'state':'confirmed','confirmed':True,'reconciliationRequired':False}
        self.centre={'providerVerified':True,'paymentMode':'centre','paymentRequired':False}
        self.online={'providerVerified':True,'paymentMode':'online','paymentRequired':True}
        self.kw={'account_id':'a1','request_key':'booking-key-00000000001'}
    def test_confirmed_booking_is_not_a_payment_receipt(self):
        with patch.object(bridge.booking,'status',return_value=self.booking):
            result=bridge.view(**self.kw)
        self.assertTrue(result['booking']['confirmed'])
        self.assertFalse(result['payment']['paid'])
        self.assertEqual(result['payment']['state'],'unverified')
    def test_centre_payment_remains_due(self):
        with patch.object(bridge.booking,'status',return_value=self.booking):
            result=bridge.view(**self.kw,payment_policy=self.centre,booking_payment_bound=True)
        self.assertEqual(result['payment']['state'],'due_at_centre')
        self.assertFalse(result['payment']['paid'])
    def test_online_requires_proven_binding_and_capture(self):
        with patch.object(bridge.booking,'status',return_value=self.booking):
            with self.assertRaises(ValueError):bridge.view(**self.kw,payment_policy=self.online,provider_state='captured',provider_verified=True)
            with self.assertRaises(ValueError):bridge.view(**self.kw,payment_policy=self.online,provider_state='captured',booking_payment_bound=True)
            result=bridge.view(**self.kw,payment_policy=self.online,provider_state='captured',provider_verified=True,booking_payment_bound=True)
        self.assertTrue(result['payment']['paid'])
    def test_account_scope_is_enforced_by_booking_status(self):
        with patch.object(bridge.booking,'status',side_effect=ValueError('booking_request_not_found')):
            with self.assertRaises(ValueError):bridge.view(**self.kw,payment_policy=self.centre,booking_payment_bound=True)
    def test_unbound_provider_state_is_rejected(self):
        with patch.object(bridge.booking,'status',return_value=self.booking):
            with self.assertRaises(ValueError):bridge.view(**self.kw,provider_state='captured',provider_verified=True)
if __name__=='__main__':unittest.main()
