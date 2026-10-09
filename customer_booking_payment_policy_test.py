import unittest
from customer_booking_payment_policy import authorize,BookingPaymentPolicyError

class Tests(unittest.TestCase):
    def test_unknown_policy_rejected(self):
        with self.assertRaises(BookingPaymentPolicyError):
            authorize(service="technical",policy={})

    def test_payment_not_required_only_if_provider_verified(self):
        result=authorize(service="technical",policy={
            "service":"technical","providerVerified":True,"paymentRequired":False})
        self.assertTrue(result["authorized"])

    def test_required_payment_without_proof_fails(self):
        with self.assertRaises(BookingPaymentPolicyError):
            authorize(service="technical",policy={
                "service":"technical","providerVerified":True,"paymentRequired":True})

    def test_required_payment_with_provider_proof(self):
        result=authorize(service="technical",policy={
            "service":"technical","providerVerified":True,"paymentRequired":True},
            payment_evidence={"providerVerified":True,"paid":True})
        self.assertTrue(result["authorized"])
