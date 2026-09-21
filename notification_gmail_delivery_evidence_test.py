import unittest
from unittest import mock

import notification_preflight as subject


class GmailDeliveryEvidenceTest(unittest.TestCase):
    def _broker(self, **overrides):
        row = {
            "transport": "email:gmail-api",
            "circuitOpen": False,
            "retryAfterSeconds": 0,
            "consecutiveFailures": 0,
            "transientFailures": 0,
            "configurationFailures": 0,
            "circuitOpens": 0,
            "lastFailureAt": "",
            "lastSuccessAt": "2026-09-21T15:00:00+00:00",
            "lastError": "must-not-leak",
        }
        row.update(overrides)
        return {"resilience": {"transports": [row]}}

    def test_real_success_is_operationally_verified(self):
        result = subject._gmail_delivery_evidence(self._broker())
        self.assertEqual(result["verification"], "verified")
        self.assertTrue(result["operationallyVerified"])
        self.assertEqual(result["lastSuccessAt"], "2026-09-21T15:00:00+00:00")
        self.assertNotIn("lastError", result)

    def test_missing_history_is_unverified(self):
        result = subject._gmail_delivery_evidence({"resilience": {"transports": []}})
        self.assertEqual(result["verification"], "unverified")
        self.assertFalse(result["operationallyVerified"])
        self.assertEqual(result["lastSuccessAt"], "")

    def test_newer_failure_invalidates_previous_success(self):
        result = subject._gmail_delivery_evidence(self._broker(
            consecutiveFailures=1,
            lastFailureAt="2026-09-21T16:00:00+00:00",
        ))
        self.assertEqual(result["verification"], "unavailable")
        self.assertFalse(result["operationallyVerified"])
        self.assertEqual(result["consecutiveFailures"], 1)

    def test_open_circuit_is_unavailable(self):
        result = subject._gmail_delivery_evidence(self._broker(circuitOpen=True))
        self.assertEqual(result["verification"], "unavailable")
        self.assertFalse(result["operationallyVerified"])

    def test_older_failure_does_not_hide_later_success(self):
        result = subject._gmail_delivery_evidence(self._broker(
            consecutiveFailures=0,
            lastFailureAt="2026-09-21T14:00:00+00:00",
        ))
        self.assertEqual(result["verification"], "verified")
        self.assertTrue(result["operationallyVerified"])

    @mock.patch.object(subject.broker, "status")
    @mock.patch.object(subject.apns, "preflight")
    @mock.patch.object(subject.email, "preflight")
    def test_run_surfaces_evidence_without_sending(self, email_preflight, apns_preflight, broker_status):
        email_preflight.return_value = {
            "ok": True,
            "activeTransport": "gmail-api",
            "transports": [{"transport": "gmail-api", "ready": True}],
        }
        apns_preflight.return_value = {
            "transport": "apns-http2",
            "ready": False,
            "state": "awaiting_configuration",
            "reason": "",
            "keyValid": False,
        }
        broker_status.return_value = self._broker()

        result = subject.run()

        self.assertEqual(result["sendsPerformed"], 0)
        self.assertEqual(result["gmailDeliveryEvidence"]["verification"], "verified")
        self.assertEqual(result["email"]["gmailDeliveryEvidence"], result["gmailDeliveryEvidence"])
        broker_status.assert_called_once_with(1)

    @mock.patch.object(subject.broker, "status", side_effect=RuntimeError("secret detail"))
    @mock.patch.object(subject.apns, "preflight")
    @mock.patch.object(subject.email, "preflight")
    def test_broker_failure_is_bounded_and_secret_free(self, email_preflight, apns_preflight, _broker_status):
        email_preflight.return_value = {"ok": True, "transports": []}
        apns_preflight.return_value = {"ready": False}

        result = subject.run()

        evidence = result["gmailDeliveryEvidence"]
        self.assertEqual(evidence["verification"], "unavailable")
        self.assertFalse(evidence["operationallyVerified"])
        self.assertNotIn("secret", repr(evidence))


if __name__ == "__main__":
    unittest.main()
