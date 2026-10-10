import unittest
from unittest.mock import patch
import customer_booking_confirmation_view as confirmation


class ConfirmationPaymentSeparationTests(unittest.TestCase):
    def test_confirmed_booking_never_claims_payment(self):
        with patch.object(confirmation, 'status', return_value={'confirmed': True}):
            result = confirmation.view(account_id='account1', request_key='booking-key-000000000001')
        self.assertTrue(result['confirmed'])
        self.assertFalse(result['paymentConfirmed'])
        self.assertIn('séparément', result['paymentMessage'])

    def test_unverified_booking_never_claims_payment(self):
        with patch.object(confirmation, 'status', return_value={'confirmed': False}):
            result = confirmation.view(account_id='account1', request_key='booking-key-000000000001')
        self.assertFalse(result['confirmed'])
        self.assertFalse(result['paymentConfirmed'])

    def test_account_scoped_lookup(self):
        with patch.object(confirmation, 'status', return_value={'confirmed': True}) as lookup:
            confirmation.view(account_id='account1', request_key='booking-key-000000000001')
        lookup.assert_called_once_with(account_id='account1', request_key='booking-key-000000000001')


if __name__ == '__main__':
    unittest.main()
