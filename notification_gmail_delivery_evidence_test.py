import unittest
from unittest import mock

import notification_preflight as subject


class GmailDeliveryEvidenceTest(unittest.TestCase):
    def _verified_evidence(self):
        return {
            "verification": "verified",
            "operationallyVerified": True,
            "lastSuccessAt": "2026-09-21T15:00:00+00:00",
            "lastFailureAt": "",
            "circuitOpen": False,
            "consecutiveFailures": 0,
        }

    @mock.patch.object(subject.gmail_evidence, "status")
    @mock.patch.object(subject.apns, "preflight")
    @mock.patch.object(subject.email, "preflight")
    def test_run_surfaces_shared_evidence_without_sending(self, email_preflight, apns_preflight, evidence_status):
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
        evidence_status.return_value = self._verified_evidence()

        result = subject.run()

        self.assertEqual(result["sendsPerformed"], 0)
        self.assertEqual(result["gmailDeliveryEvidence"]["verification"], "verified")
        self.assertEqual(result["email"]["gmailDeliveryEvidence"], result["gmailDeliveryEvidence"])
        evidence_status.assert_called_once_with()

    @mock.patch.object(subject.gmail_evidence, "status", side_effect=RuntimeError("secret detail"))
    @mock.patch.object(subject.apns, "preflight")
    @mock.patch.object(subject.email, "preflight")
    def test_evidence_failure_is_bounded_and_secret_free(self, email_preflight, apns_preflight, _evidence_status):
        email_preflight.return_value = {"ok": True, "transports": []}
        apns_preflight.return_value = {"ready": False}

        result = subject.run()

        evidence = result["gmailDeliveryEvidence"]
        self.assertEqual(evidence["verification"], "unavailable")
        self.assertFalse(evidence["operationallyVerified"])
        self.assertNotIn("secret", repr(evidence))


if __name__ == "__main__":
    unittest.main()
