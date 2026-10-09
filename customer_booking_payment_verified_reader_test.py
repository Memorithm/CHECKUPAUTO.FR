import unittest
from unittest.mock import Mock, patch
import customer_booking_payment_verified_reader as reader

class Tests(unittest.TestCase):
    def setUp(self):
        self.kw={'account_id':'a1','request_key':'booking-key-000000000001','expected_amount_cents':8000}
        self.assoc={'bound':True,'paymentRef':'a'*32,'provider':'payline'}
        self.intent=Mock(provider='payline',environment='sandbox',amount_cents=8000,state='captured',provider_reference='tok123')
        self.transaction={'provider':'payline','capturedAmountCents':8000,'transactionId':'tx123'}
    def test_unbound_booking_never_reads_journal(self):
        with patch.object(reader.binding,'lookup',return_value={'bound':False}),patch.object(reader,'SandboxJournal') as journal:
            with self.assertRaisesRegex(ValueError,'binding_missing'):reader.read(**self.kw)
            journal.assert_not_called()
    def test_captured_requires_transaction_record(self):
        with patch.object(reader.binding,'lookup',return_value=self.assoc),patch.object(reader,'SandboxJournal') as cls:
            cls.return_value.get.return_value=self.intent
            cls.return_value.provider_transaction.return_value=self.transaction
            self.assertTrue(reader.read(**self.kw)['paid'])
            cls.return_value.get.assert_called_once_with('a'*32)
    def test_missing_transaction_never_claims_paid(self):
        with patch.object(reader.binding,'lookup',return_value=self.assoc),patch.object(reader,'SandboxJournal') as cls:
            cls.return_value.get.return_value=self.intent
            cls.return_value.provider_transaction.side_effect=reader.PaymentError('missing')
            with self.assertRaisesRegex(ValueError,'transaction_unverified'):reader.read(**self.kw)
    def test_mismatched_capture_amount_rejected(self):
        with patch.object(reader.binding,'lookup',return_value=self.assoc),patch.object(reader,'SandboxJournal') as cls:
            cls.return_value.get.return_value=self.intent
            cls.return_value.provider_transaction.return_value=self.transaction | {'capturedAmountCents':7900}
            with self.assertRaisesRegex(ValueError,'capture_mismatch'):reader.read(**self.kw)
    def test_pending_is_not_paid(self):
        self.intent.state='pending'
        with patch.object(reader.binding,'lookup',return_value=self.assoc),patch.object(reader,'SandboxJournal') as cls:
            cls.return_value.get.return_value=self.intent
            self.assertFalse(reader.read(**self.kw)['paid'])
            cls.return_value.provider_transaction.assert_not_called()
    def test_sandbox_only(self):
        self.intent.environment='live'
        with patch.object(reader.binding,'lookup',return_value=self.assoc),patch.object(reader,'SandboxJournal') as cls:
            cls.return_value.get.return_value=self.intent
            with self.assertRaisesRegex(ValueError,'intent_mismatch'):reader.read(**self.kw)
if __name__=='__main__':unittest.main()
