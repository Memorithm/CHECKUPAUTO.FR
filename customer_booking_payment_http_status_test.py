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
        with patch.object(api.booking,'status',return_value={'confirmed':True}),patch.object(api.binding,'lookup',return_value={'bound':True}),patch.object(api.reader,'read') as reader:
            result=api.status(**self.kw)
        self.assertEqual(result['payment']['state'],'bound_unverified');self.assertFalse(result['payment']['paid']);reader.assert_not_called()
    def test_foreign_account_failure_is_not_suppressed(self):
        with patch.object(api.booking,'status',side_effect=ValueError('not_found')):
            with self.assertRaises(ValueError):api.status(**self.kw)
if __name__=='__main__':unittest.main()
