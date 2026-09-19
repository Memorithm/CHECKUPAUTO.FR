import json
import unittest
from unittest import mock

import production_readiness as readiness


CONFIG = {"seo": {"canonicalUrl": "https://www.checkupauto.fr/"}}
SEO_READY = {"totals": {"pass": 16, "warning": 0, "fail": 0}}


def healthy_patches():
    return [
        mock.patch.object(readiness.reminder_dispatch, "status", return_value={
            "ok": True, "sessionConnected": True, "backfillComplete": True,
            "inventory": 2022, "futureDueDates": 1600, "eligibleNow": 0,
        }),
        mock.patch.object(readiness.notification_broker, "status", return_value={
            "channels": {
                "email": {"configured": True, "transport": "gmail-api"},
                "push": {"configured": True},
            },
            "resilience": {"circuitsOpen": 0, "permanentFailures": 0},
        }),
        mock.patch.object(readiness.app_download, "status", return_value={
            "ios": {"available": True, "channel": "app-store", "targetUrl": "https://apps.apple.com/app/id123"},
        }),
        mock.patch.object(readiness.mobile_claim_delivery, "status", return_value={
            "ready": True, "domain": "www.checkupauto.fr", "claimPath": "/app/claim",
        }),
        mock.patch.object(readiness.gsc_client, "credential_info", return_value={}),
        mock.patch.object(readiness.integration_hub, "status", return_value={
            "oauthAuthorized": True, "connectors": [{"connected": True}],
        }),
        mock.patch.object(readiness.analytics_store, "summary", return_value={"pageViews": 7, "bookingClicks": 1}),
        mock.patch.object(readiness.referral_engine, "list_accounts", return_value=[]),
        mock.patch.object(readiness.referral_engine, "configured_reward_cents", return_value=500),
        mock.patch.object(readiness.review_followup, "status", return_value={
            "emailTransportConfigured": True, "reviewUrlConfigured": True, "sentTotal": 3,
        }),
        mock.patch.object(readiness.security_integrity, "posture", return_value={
            "ok": True, "vulnerabilities": {"count": 0},
        }),
        mock.patch.object(readiness.security_alerts, "summary", return_value={
            "open": 0, "undeliveredHighOrCritical": 0,
        }),
    ]


class ProductionReadinessTest(unittest.TestCase):
    def _run_with(self, patches, seo=SEO_READY):
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        return readiness.status(CONFIG, seo)

    def test_all_ready_is_launch_ready(self):
        result = self._run_with(healthy_patches())
        self.assertTrue(result["ok"])
        self.assertEqual(result["state"], "ready")
        self.assertTrue(result["launchReady"])
        self.assertEqual(result["blockers"], [])
        self.assertEqual(result["counts"]["ready"], len(result["components"]))

    def test_external_and_configuration_blockers_are_distinct(self):
        patches = healthy_patches()
        patches[1] = mock.patch.object(readiness.notification_broker, "status", return_value={
            "channels": {
                "email": {"configured": False, "transport": "none"},
                "push": {"configured": False},
            },
            "resilience": {"circuitsOpen": 0, "permanentFailures": 0},
        })
        patches[2] = mock.patch.object(readiness.app_download, "status", return_value={
            "ios": {"available": False, "channel": "pending", "targetUrl": None},
        })
        patches[3] = mock.patch.object(readiness.mobile_claim_delivery, "status", return_value={
            "ready": False, "domain": "www.checkupauto.fr", "claimPath": "/app/claim",
        })
        patches[5] = mock.patch.object(readiness.integration_hub, "status", return_value={
            "oauthAuthorized": False, "connectors": [{"connected": False}],
        })
        patches[9] = mock.patch.object(readiness.review_followup, "status", return_value={
            "emailTransportConfigured": False, "reviewUrlConfigured": False, "sentTotal": 0,
        })
        result = self._run_with(patches, {"totals": {"pass": 9, "warning": 7, "fail": 0}})
        states = {item["id"]: item["state"] for item in result["components"]}
        self.assertEqual(states["email_delivery"], "configuration_required")
        self.assertEqual(states["apns"], "configuration_required")
        self.assertEqual(states["ios_distribution"], "blocked_external")
        self.assertEqual(states["ios_claim"], "configuration_required")
        self.assertEqual(states["google_integration"], "configuration_required")
        self.assertEqual(states["seo"], "configuration_required")
        self.assertEqual(result["state"], "blocked_external")
        self.assertFalse(result["launchReady"])

    def test_probe_exception_is_degraded_without_leaking_message(self):
        patches = healthy_patches()
        patches[1] = mock.patch.object(readiness.notification_broker, "status", side_effect=RuntimeError("secret-token-123"))
        result = self._run_with(patches)
        states = {item["id"]: item["state"] for item in result["components"]}
        self.assertEqual(states["notification_broker"], "degraded")
        self.assertEqual(result["state"], "degraded")
        self.assertFalse(result["launchReady"])
        self.assertNotIn("secret-token-123", json.dumps(result))
        self.assertIn("RuntimeError", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
