import unittest
from unittest.mock import patch
import customer_booking_payment_http_status as api

class Tests(unittest.TestCase):
    def setUp(self):self.kw={'account_id':'a1','request_key':'booking-key-000000000001'}
    def test_unconfirmed_never_queries_binding(self):
        with patch.object(api.booking,'status',return_value={'confirmed':False}),patch.object(api.binding,'lookup') as lookup:
            result=api.status(**self.kw)
        self.assertFalse(result['payment']['paid']);lookup.assert_not_called()
    def test_confirmed_booking_without_binding_remains_unpaid(self):
        with patch.object(api.booking,'status',return_value={'confirmed':True}),patch.object(api.binding,'lookup',return_value={'bound':False}):
            result=api.status(**self.kw)
        self.assertEqual(result['payment']['state'],'unverified')
    def test_bound_sandbox_reference_is_not_capture(self):
        with patch.object(api.booking,'status',return_value={'confirmed':True}),patch.object(api.binding,'lookup',return_value={'bound':True,'providerBookingRef':'mercure_123'}),patch.object(api.booking_bridge,'authoritative_payment_basis',side_effect=ValueError('not_found')),patch.object(api.reader,'read') as reader:
            result=api.status(**self.kw)
        self.assertEqual(result['payment']['state'],'bound_unverified');self.assertFalse(result['payment']['paid']);reader.assert_not_called()
    def test_foreign_account_failure_is_not_suppressed(self):
        with patch.object(api.booking,'status',side_effect=ValueError('not_found')):
            with self.assertRaises(ValueError):api.status(**self.kw)
if __name__=='__main__':unittest.main()

class VerifiedStatusTests(unittest.TestCase):
    def setUp(self):
        self.kw={'account_id':'a1','request_key':'booking-key-000000000001'}
        self.associated={'bound':True,'providerBookingRef':'mercure_123'}
        self.basis={'provider':api.booking_bridge.PROVIDER,'status':next(iter(api.booking_bridge.CONFIRMED)),
                    'amountCents':8000}
    def test_verified_capture_uses_authoritative_amount(self):
        with patch.object(api.booking,'status',return_value={'confirmed':True}),patch.object(api.binding,'lookup',return_value=self.associated),patch.object(api.booking_bridge,'authoritative_payment_basis',return_value=self.basis),patch.object(api.reader,'read',return_value={'state':'captured','paid':True,'providerVerified':True,'bookingPaymentBound':True}) as reader:
            result=api.status(**self.kw)
        self.assertTrue(result['payment']['paid'])
        reader.assert_called_once_with(**self.kw,expected_amount_cents=8000)
    def test_unverified_provider_capture_stays_unpaid(self):
        with patch.object(api.booking,'status',return_value={'confirmed':True}),patch.object(api.binding,'lookup',return_value=self.associated),patch.object(api.booking_bridge,'authoritative_payment_basis',return_value=self.basis),patch.object(api.reader,'read',return_value={'state':'captured','paid':True,'providerVerified':False,'bookingPaymentBound':True}):
            result=api.status(**self.kw)
        self.assertFalse(result['payment']['paid'])
    def test_missing_authoritative_quote_blocks_capture(self):
        with patch.object(api.booking,'status',return_value={'confirmed':True}),patch.object(api.binding,'lookup',return_value=self.associated),patch.object(api.booking_bridge,'authoritative_payment_basis',side_effect=ValueError('missing')),patch.object(api.reader,'read') as reader:
            result=api.status(**self.kw)
        self.assertFalse(result['payment']['paid'])
        reader.assert_not_called()
