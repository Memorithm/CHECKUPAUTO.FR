import unittest
from customer_booking_payment_policy import authorize,BookingPaymentPolicyError

class Tests(unittest.TestCase):
    def test_unknown_policy_rejected(self):
        with self.assertRaises(BookingPaymentPolicyError):
            authorize(service="technical",policy={})

    def test_centre_payment_rejected_even_if_provider_verified(self):
        with self.assertRaisesRegex(BookingPaymentPolicyError, "booking_online_payment_required"):
            authorize(service="technical",policy={"service":"technical",
                "providerVerified":True,"paymentRequired":False,"paymentMode":"centre"})

    def test_required_payment_without_proof_fails(self):
        with self.assertRaises(BookingPaymentPolicyError):
            authorize(service="technical",policy={
                "service":"technical","providerVerified":True,"paymentRequired":True})

    def test_required_payment_with_provider_proof(self):
        result=authorize(service="technical",policy={
            "service":"technical","providerVerified":True,"paymentRequired":True},
            payment_evidence={"providerVerified":True,"paid":True})
        self.assertTrue(result["authorized"])
