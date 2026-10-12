import os
import tempfile
import unittest
from unittest.mock import patch
import customer_booking_payment_binding as binding

class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {'CYBERCHECK_DATA_DIR':self.temp.name})
        self.env.start();self.addCleanup(self.env.stop)
        self.kw = dict(account_id='a1',request_key='booking-key-000000000001',provider_booking_ref='mercure_123',payment_ref='pay_123',payment_provider='payline')
        self.book = patch.object(binding,'booking_status',return_value={'confirmed':True,'providerReference':'mercure_123'})
        self.book.start();self.addCleanup(self.book.stop)
    def test_authorization_required(self):
        with self.assertRaisesRegex(ValueError,'not_authorized'):binding.bind(**self.kw)
    def test_exact_binding_is_idempotent_and_unpaid(self):
        first=binding.bind(**self.kw,authorized=True)
        second=binding.bind(**self.kw,authorized=True)
        self.assertEqual(first,second)
        self.assertFalse(first['paid'])
        self.assertTrue(binding.lookup(account_id='a1',request_key=self.kw['request_key'])['bound'])
    def test_conflicting_payment_is_rejected(self):
        binding.bind(**self.kw,authorized=True)
        with self.assertRaisesRegex(ValueError,'conflict'):
            binding.bind(**(self.kw | {'payment_ref':'other_123'}),authorized=True)
    def test_reference_cannot_bind_another_booking(self):
        binding.bind(**self.kw,authorized=True)
        with self.assertRaises(Exception):
            binding.bind(**(self.kw | {'request_key':'booking-key-000000000002'}),authorized=True)
    def test_unconfirmed_booking_rejected(self):
        with patch.object(binding,'booking_status',return_value={'confirmed':False}):
            with self.assertRaisesRegex(ValueError,'not_independently_confirmed'):
                binding.bind(**self.kw,authorized=True)
    def test_foreign_account_cannot_see_binding(self):
        binding.bind(**self.kw,authorized=True)
        self.assertFalse(binding.lookup(account_id='a2',request_key=self.kw['request_key'])['bound'])
    def test_payment_reference_routes_back_to_its_request_key_only(self):
        self.assertIsNone(binding.request_key_for_payment('pay_123'))
        binding.bind(**self.kw,authorized=True)
        self.assertEqual(binding.request_key_for_payment('pay_123'),self.kw['request_key'])
        self.assertIsNone(binding.request_key_for_payment('other_123'))
        with self.assertRaises(ValueError):
            binding.request_key_for_payment('../x')
if __name__=='__main__':unittest.main()
