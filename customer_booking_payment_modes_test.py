import unittest
from mercure_vl_payment_policy_source import qualify, MercurePaymentPolicyError
from customer_booking_payment_policy import authorize, BookingPaymentPolicyError


class Tests(unittest.TestCase):
    def test_centre_only_is_unavailable_for_checkupauto(self):
        with self.assertRaisesRegex(MercurePaymentPolicyError, 'online_payment_unavailable'):
            qualify(service='technical', response={'paiementCentre': True, 'paiementWeb': False})

    def test_online_requires_verified_payment(self):
        policy = qualify(service='technical', response={'paiementCentre': True, 'paiementWeb': True})
        self.assertEqual(policy['paymentMode'], 'online')
        with self.assertRaisesRegex(BookingPaymentPolicyError, 'evidence_missing'):
            authorize(service='technical', policy=policy)
        result = authorize(service='technical', policy=policy,
                           payment_evidence={'providerVerified': True, 'paid': True})
        self.assertTrue(result['paid'])

    def test_no_payment_option_fails_closed(self):
        with self.assertRaisesRegex(MercurePaymentPolicyError, 'online_payment_unavailable'):
            qualify(service='technical', response={'paiementCentre': False, 'paiementWeb': False})

    def test_centre_payment_cannot_be_authorized_even_with_receipt(self):
        policy = {'service': 'technical', 'providerVerified': True,
                  'paymentRequired': False, 'paymentMode': 'centre'}
        with self.assertRaisesRegex(BookingPaymentPolicyError, 'online_payment_required'):
            authorize(service='technical', policy=policy,
                      payment_evidence={'paid': True, 'providerVerified': True})

    def test_inconsistent_mode_policy_is_rejected(self):
        with self.assertRaisesRegex(BookingPaymentPolicyError, 'online_payment_required'):
            authorize(service='technical', policy={'service': 'technical',
                'providerVerified': True, 'paymentRequired': False, 'paymentMode': 'online'})


if __name__ == '__main__':
    unittest.main()
