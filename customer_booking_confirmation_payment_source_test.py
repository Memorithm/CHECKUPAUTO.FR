import unittest
from unittest.mock import patch
import customer_booking_confirmation_payment_source as source


class Tests(unittest.TestCase):
    def setUp(self):
        self.kw = {'account_id': 'account1', 'request_key': 'booking-key-000000000001'}
        self.booking = {'confirmed': True, 'providerReference': '12345'}
        self.basis = {'provider': source.booking_bridge.PROVIDER,
                      'status': 'confirmed', 'service': 'technical',
                      'bookingReference': 'mercure:verified'}
        self.policy = {'service': 'technical', 'providerVerified': True,
                       'paymentMode': 'centre', 'paymentRequired': False}

    def test_confirmed_owned_booking_uses_independent_service(self):
        with patch.object(source.journal, 'status', return_value=self.booking) as status, \
             patch.object(source.booking_bridge, 'authoritative_payment_basis', return_value=self.basis), \
             patch.object(source.booking_bridge, 'booking_reference_for_external_id', return_value='mercure:verified'), \
             patch.object(source.payment_source, 'load', return_value=self.policy) as policy:
            self.assertEqual(source.load(**self.kw), self.policy)
        status.assert_called_once_with(account_id='account1', key=self.kw['request_key'])
        policy.assert_called_once_with(service='technical')

    def test_unconfirmed_booking_never_contacts_provider(self):
        with patch.object(source.journal, 'status', return_value={'confirmed': False}), \
             patch.object(source.payment_source, 'load') as payment:
            self.assertIsNone(source.load(**self.kw))
        payment.assert_not_called()

    def test_foreign_booking_identity_is_rejected(self):
        with patch.object(source.journal, 'status', return_value=self.booking), \
             patch.object(source.booking_bridge, 'authoritative_payment_basis', return_value=self.basis), \
             patch.object(source.booking_bridge, 'booking_reference_for_external_id', return_value='mercure:other'), \
             patch.object(source.payment_source, 'load') as payment:
            self.assertIsNone(source.load(**self.kw))
        payment.assert_not_called()

    def test_unavailable_provider_policy_is_not_guessed(self):
        with patch.object(source.journal, 'status', return_value=self.booking), \
             patch.object(source.booking_bridge, 'authoritative_payment_basis', return_value=self.basis), \
             patch.object(source.booking_bridge, 'booking_reference_for_external_id', return_value='mercure:verified'), \
             patch.object(source.payment_source, 'load', side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):
                source.load(**self.kw)

    def test_foreign_account_is_not_silently_accepted(self):
        with patch.object(source.journal, 'status', side_effect=ValueError('booking_request_not_found')):
            with self.assertRaisesRegex(ValueError, 'booking_request_not_found'):
                source.load(**self.kw)


if __name__ == '__main__':
    unittest.main()
