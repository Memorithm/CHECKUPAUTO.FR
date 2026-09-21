import contextlib
import unittest
from unittest import mock

import production_readiness as readiness


CONFIG = {"seo": {"canonicalUrl": "https://www.checkupauto.fr/"}}
SEO_READY = {"totals": {"pass": 16, "warning": 0, "fail": 0}}


def healthy_patches(reminder):
    return [
        mock.patch.object(readiness.reminder_dispatch, "status", return_value=reminder),
        mock.patch.object(readiness.notification_broker, "status", return_value={
            "channels": {
                "email": {"configured": True, "transport": "gmail-api"},
                "push": {"configured": True},
            },
            "resilience": {"circuitsOpen": 0, "permanentFailures": 0},
            "failureCounts": {},
        }),
        mock.patch.object(readiness.notification_preflight, "run", return_value={
            "email": {"ok": True, "state": "ready"},
            "push": {"ready": True, "state": "ready", "keyValid": True},
        }),
        mock.patch.object(readiness.app_download, "status", return_value={
            "ios": {"available": True, "channel": "app-store", "targetUrl": "https://apps.apple.com/app/id123"},
        }),
        mock.patch.object(readiness.mobile_claim_delivery, "status", return_value={
            "ready": True, "domain": "www.checkupauto.fr", "claimPath": "/app/claim",
        }),
        mock.patch.object(readiness.ios_release_preflight, "status", return_value={
            "state": "ready", "projectReady": True, "associationReady": True,
            "publicationReady": True, "channel": "app-store", "checks": [],
        }),
        mock.patch.object(readiness.gsc_client, "credential_info", return_value={}),
        mock.patch.object(readiness.integration_hub, "status", return_value={
            "oauthAuthorized": True,
            "oauthHealth": {"state": "ready", "usable": True},
            "connectors": [{"connected": True}],
        }),
        mock.patch.object(readiness.analytics_store, "summary", return_value={"pageViews": 7, "bookingClicks": 1}),
        mock.patch.object(readiness.referral_engine, "list_accounts", return_value=[]),
        mock.patch.object(readiness.referral_engine, "configured_reward_cents", return_value=500),
        mock.patch.object(readiness.referral_integrity_audit, "status", return_value={
            "ok": True, "state": "ready", "issues": 0, "metrics": {},
        }),
        mock.patch.object(readiness.review_followup, "status", return_value={
            "emailTransportConfigured": True,
            "emailTransportReady": True,
            "emailPreflightState": "ready",
            "reviewUrlConfigured": True,
            "sentTotal": 0,
        }),
        mock.patch.object(readiness.security_integrity, "posture", return_value={
            "ok": True, "vulnerabilities": {"count": 0},
        }),
        mock.patch.object(readiness.security_alerts, "summary", return_value={
            "open": 0,
            "undeliveredHighOrCritical": 0,
            "delivery": {
                "configured": True,
                "ready": True,
                "state": "ready",
                "signed": True,
                "endpointHost": "alerts.example.test",
            },
        }),
        mock.patch.object(readiness.admin_mfa, "configured", return_value=True),
        mock.patch.object(readiness.admin_mfa, "recovery_remaining", return_value=10),
        mock.patch.object(readiness.compliance_admin, "snapshot", return_value={
            "summary": {
                "readyForPublicContracting": True,
                "operationalRegistersReady": True,
                "identityComplete": True,
                "publishedDocuments": 4,
                "requiredDocuments": 4,
                "checkoutAcceptanceBound": True,
                "withdrawalFunctionBound": True,
                "overdueRightsRequests": 0,
                "overdueIncidentNotifications": 0,
                "operationalBlockers": [],
            },
        }),
    ]


class ReminderQuarantineReadinessTest(unittest.TestCase):
    def _status(self, quarantined):
        reminder = {
            "ok": True,
            "sessionConnected": True,
            "backfillComplete": True,
            "inventory": 12,
            "quarantinedTargets": quarantined,
            "futureDueDates": 8,
            "eligibleNow": 2,
        }
        with contextlib.ExitStack() as stack:
            for patcher in healthy_patches(reminder):
                stack.enter_context(patcher)
            return readiness.status(CONFIG, SEO_READY)

    def test_quarantined_identity_closes_activation_gate(self):
        result = self._status(2)
        component = next(item for item in result["components"] if item["id"] == "reminder_engine")

        self.assertEqual(component["state"], "degraded")
        self.assertEqual(component["metrics"]["quarantinedTargets"], 2)
        self.assertIn("quarantaine", component["detail"])
        self.assertIn("quarantinedTargets=0", component["remediation"]["verify"])
        self.assertIn("reminder_engine", result["criticalBlockers"])
        self.assertFalse(result["activationGate"]["allowed"])

    def test_zero_quarantine_preserves_ready_state(self):
        result = self._status(0)
        component = next(item for item in result["components"] if item["id"] == "reminder_engine")

        self.assertEqual(component["state"], "ready")
        self.assertEqual(component["metrics"]["quarantinedTargets"], 0)
        self.assertNotIn("reminder_engine", result["criticalBlockers"])
        self.assertTrue(result["activationGate"]["allowed"])


if __name__ == "__main__":
    unittest.main()
