import unittest
from unittest.mock import Mock, patch
import customer_booking_create_api as api


class Tests(unittest.TestCase):
    def setUp(self):
        self.payload = dict(service="technical", date="2026-10-15", time="09:00",
                            vehicleId="v1", requestKey="booking-prepaid-verified-00001")
        self.account = {"accountId": "a1", "vehicles": [{"vehicleId": "v1"}]}
        self.context = dict(metadata={}, observed_metadata={}, service_label="CT",
                            slot_evidence={"observed": True},
                            payment_policy={"service": "technical", "providerVerified": True,
                                            "paymentRequired": True, "paymentMode": "online"},
                            payment_evidence={"providerVerified": True, "paid": True})

    def run_booking(self, context):
        writer = Mock(return_value={"confirmed": True})
        with patch.object(api.customer_booking_api, "preflight",
                          return_value={"bookingEnabled": True, "service": "technical",
                                        "priceCents": 8000}), patch.object(
                          api.in_site_booking_readiness, "public_status",
                          return_value={"bookingEnabled": True}):
            try:
                result = api.create(self.payload, account=self.account,
                                    executor=writer, trusted_context=context)
                return result, writer
            except api.BookingCreateUnavailable:
                return None, writer

    def test_missing_payment_proof_never_writes(self):
        result, writer = self.run_booking(self.context | {"payment_evidence": None})
        self.assertIsNone(result)
        writer.assert_not_called()

    def test_unverified_payment_never_writes(self):
        result, writer = self.run_booking(self.context | {
            "payment_evidence": {"providerVerified": False, "paid": True}})
        self.assertIsNone(result)
        writer.assert_not_called()

    def test_centre_only_policy_never_writes(self):
        result, writer = self.run_booking(self.context | {
            "payment_policy": {"service": "technical", "providerVerified": True,
                               "paymentRequired": False, "paymentMode": "centre"}})
        self.assertIsNone(result)
        writer.assert_not_called()

    def test_verified_prepayment_allows_qualified_writer(self):
        result, writer = self.run_booking(self.context)
        self.assertTrue(result["confirmed"])
        self.assertTrue(result["paymentConfirmed"])
        self.assertEqual(result["paymentDue"], "none")
        writer.assert_called_once()


if __name__ == "__main__":
    unittest.main()
