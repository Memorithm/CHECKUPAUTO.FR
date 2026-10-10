import unittest
from unittest.mock import patch
import customer_booking_confirmation_view as confirmation


class CentreConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.kw = {'account_id': 'account1', 'request_key': 'booking-key-000000000001'}
        self.policy = {'service': 'technical', 'providerVerified': True,
                       'paymentMode': 'centre', 'paymentRequired': False}

    def test_confirmed_booking_with_centre_policy_shows_due_at_centre(self):
        with patch.object(confirmation, 'status', return_value={'confirmed': True}):
            result = confirmation.view(**self.kw, payment_status=self.policy)
        self.assertEqual(result['paymentMessage'], 'Paiement à effectuer au centre le jour du rendez-vous')
        self.assertFalse(result['paymentConfirmed'])

    def test_unverified_centre_policy_does_not_claim_centre_payment(self):
        with patch.object(confirmation, 'status', return_value={'confirmed': True}):
            result = confirmation.view(**self.kw, payment_status=self.policy | {'providerVerified': False})
        self.assertIn('vérifier séparément', result['paymentMessage'])

    def test_online_payment_does_not_show_centre_message(self):
        with patch.object(confirmation, 'status', return_value={'confirmed': True}):
            result = confirmation.view(**self.kw, payment_status=self.policy | {'paymentMode': 'online', 'paymentRequired': True})
        self.assertIn('vérifier séparément', result['paymentMessage'])

    def test_pending_booking_does_not_claim_payment_mode(self):
        with patch.object(confirmation, 'status', return_value={'confirmed': False}):
            result = confirmation.view(**self.kw, payment_status=self.policy)
        self.assertFalse(result['confirmed'])
        self.assertFalse(result['paymentConfirmed'])
        self.assertNotIn('paymentMessage', result)


if __name__ == '__main__':
    unittest.main()
