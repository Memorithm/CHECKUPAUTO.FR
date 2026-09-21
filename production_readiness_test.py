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
        mock.patch.object(readiness.gsc_client, "credential_info", return_value={}),
        mock.patch.object(readiness.integration_hub, "status", return_value={
            "oauthAuthorized": True,
            "oauthHealth": {"state": "ready", "usable": True},
            "oauthClient": {"webClientVerified": True, "redirectUriCount": 1},
            "connectors": [{"connected": True}],
        }),
        mock.patch.object(readiness.analytics_store, "summary", return_value={"pageViews": 7, "bookingClicks": 1}),
        mock.patch.object(readiness.referral_engine, "list_accounts", return_value=[]),
        mock.patch.object(readiness.referral_engine, "configured_reward_cents", return_value=500),
        mock.patch.object(readiness.review_followup, "status", return_value={
            "emailTransportConfigured": True, "emailTransportReady": True, "emailPreflightState": "ready", "reviewUrlConfigured": True, "sentTotal": 3,
        }),
        mock.patch.object(readiness.security_integrity, "posture", return_value={
            "ok": True, "vulnerabilities": {"count": 0},
        }),
        mock.patch.object(readiness.security_alerts, "summary", return_value={
            "open": 0, "undeliveredHighOrCritical": 0,
            "delivery": {"configured": True, "ready": True, "state": "ready", "signed": True, "endpointHost": "alerts.example.test"},
        }),
        mock.patch.object(readiness.ios_release_preflight, "status", return_value={
            "state": "ready", "projectReady": True, "associationReady": True,
            "publicationReady": True, "channel": "app-store", "checks": [],
        }),
    ]


class ProductionReadinessTest(unittest.TestCase):
    def _run_with(self, patches, seo=SEO_READY):
        audit_patcher = mock.patch.object(readiness.referral_integrity_audit, "status", return_value={
            "ok": True, "state": "ready", "issues": 0, "metrics": {"accountsInDebt": 0},
        })
        audit_patcher.start()
        self.addCleanup(audit_patcher.stop)
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        return readiness.status(CONFIG, seo)

    def test_all_ready_is_launch_ready(self):
        result = self._run_with(healthy_patches())
        self.assertTrue(result["ok"])
        self.assertEqual(result["state"], "ready")
        self.assertTrue(result["launchReady"])
        self.assertEqual(result["schemaVersion"], 2)
        self.assertEqual(result["blockers"], [])
        self.assertEqual(result["criticalBlockers"], [])
        self.assertTrue(result["activationGate"]["allowed"])
        self.assertEqual(result["activationGate"]["state"], "open")
        self.assertEqual(result["counts"]["ready"], len(result["components"]))
        self.assertTrue(all(item["remediation"] is None for item in result["components"]))

    def test_external_and_configuration_blockers_are_distinct(self):
        patches = healthy_patches()
        patches[1] = mock.patch.object(readiness.notification_broker, "status", return_value={
            "channels": {
                "email": {"configured": False, "transport": "none"},
                "push": {"configured": False},
            },
            "resilience": {"circuitsOpen": 0, "permanentFailures": 0},
        })
        patches[2] = mock.patch.object(readiness.notification_preflight, "run", return_value={
            "email": {"ok": False, "state": "awaiting_configuration"},
            "push": {"ready": False, "state": "awaiting_credentials", "keyValid": False},
        })
        patches[3] = mock.patch.object(readiness.app_download, "status", return_value={
            "ios": {"available": False, "channel": "pending", "targetUrl": None},
        })
        patches[4] = mock.patch.object(readiness.mobile_claim_delivery, "status", return_value={
            "ready": False, "domain": "www.checkupauto.fr", "claimPath": "/app/claim",
        })
        patches[6] = mock.patch.object(readiness.integration_hub, "status", return_value={
            "oauthAuthorized": False, "connectors": [{"connected": False}],
        })
        patches[10] = mock.patch.object(readiness.review_followup, "status", return_value={
            "emailTransportConfigured": False, "emailTransportReady": False, "emailPreflightState": "awaiting_configuration", "reviewUrlConfigured": False, "sentTotal": 0,
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
        self.assertEqual(result["criticalBlockers"], ["email_delivery"])
        self.assertFalse(result["activationGate"]["allowed"])
        email = next(item for item in result["components"] if item["id"] == "email_delivery")
        self.assertEqual(email["remediation"]["code"], "configure_email_transport")
        self.assertTrue(email["remediation"]["external"])

    def test_authorized_google_oauth_with_unverified_web_client_is_degraded_without_blocking_launch(self):
        patches = healthy_patches()
        patches[6] = mock.patch.object(readiness.integration_hub, "status", return_value={
            "oauthAuthorized": True,
            "oauthHealth": {"state": "ready", "usable": True},
            "oauthClient": {"configured": True, "webClientVerified": False, "redirectUriCount": 0},
            "connectors": [{"connected": True}],
        })
        result = self._run_with(patches)
        google = next(item for item in result["components"] if item["id"] == "google_integration")
        self.assertEqual(google["state"], "degraded")
        self.assertFalse(google["metrics"]["webClientVerified"])
        self.assertEqual(google["metrics"]["redirectUriCount"], 0)
        self.assertIn("Application Web", google["detail"])
        self.assertTrue(result["activationGate"]["allowed"])

    def test_non_oauth_google_connector_does_not_require_web_client(self):
        patches = healthy_patches()
        patches[6] = mock.patch.object(readiness.integration_hub, "status", return_value={
            "oauthAuthorized": False,
            "oauthHealth": {"state": "awaiting_authorization", "usable": False},
            "oauthClient": {"configured": False, "webClientVerified": False, "redirectUriCount": 0},
            "connectors": [{"connected": True}],
        })
        result = self._run_with(patches)
        google = next(item for item in result["components"] if item["id"] == "google_integration")
        self.assertEqual(google["state"], "ready")
        self.assertFalse(google["metrics"]["webClientVerified"])
        self.assertEqual(google["metrics"]["redirectUriCount"], 0)
        self.assertTrue(result["activationGate"]["allowed"])

    def test_stale_google_oauth_is_degraded_without_blocking_launch(self):
        patches = healthy_patches()
        patches[6] = mock.patch.object(readiness.integration_hub, "status", return_value={
            "oauthAuthorized": False,
            "oauthHealth": {"state": "token_expired", "usable": False},
            "connectors": [{"connected": False}],
        })
        result = self._run_with(patches)
        google = next(item for item in result["components"] if item["id"] == "google_integration")
        self.assertEqual(google["state"], "degraded")
        self.assertEqual(google["metrics"]["oauthState"], "token_expired")
        self.assertTrue(result["activationGate"]["allowed"])


    def test_noncritical_blockers_do_not_close_activation_gate(self):
        patches = healthy_patches()
        patches[1] = mock.patch.object(readiness.notification_broker, "status", return_value={
            "channels": {
                "email": {"configured": True, "transport": "gmail-api"},
                "push": {"configured": False},
            },
            "resilience": {"circuitsOpen": 0, "permanentFailures": 0},
        })
        patches[2] = mock.patch.object(readiness.notification_preflight, "run", return_value={
            "email": {"ok": True, "state": "ready"},
            "push": {"ready": False, "state": "awaiting_credentials", "keyValid": False},
        })
        patches[3] = mock.patch.object(readiness.app_download, "status", return_value={
            "ios": {"available": False, "channel": "pending", "targetUrl": None},
        })
        result = self._run_with(patches)
        self.assertEqual(result["state"], "blocked_external")
        self.assertTrue(result["launchReady"])
        self.assertEqual(result["criticalBlockers"], [])
        self.assertTrue(result["activationGate"]["allowed"])

    def test_require_activation_raises_only_with_critical_blockers(self):
        patches = healthy_patches()
        patches[1] = mock.patch.object(readiness.notification_broker, "status", return_value={
            "channels": {
                "email": {"configured": False, "transport": "none"},
                "push": {"configured": False},
            },
            "resilience": {"circuitsOpen": 0, "permanentFailures": 0},
        })
        patches[2] = mock.patch.object(readiness.notification_preflight, "run", return_value={
            "email": {"ok": False, "state": "awaiting_configuration"},
            "push": {"ready": False, "state": "awaiting_credentials", "keyValid": False},
        })
        report = self._run_with(patches)
        with self.assertRaises(readiness.ProductionActivationBlocked) as ctx:
            readiness.require_activation(report)
        self.assertEqual(ctx.exception.blockers, ("email_delivery",))
        self.assertNotIn("SMTP", str(ctx.exception))


    def test_permanent_notification_failures_degrade_critical_broker(self):
        patches = healthy_patches()
        patches[1] = mock.patch.object(readiness.notification_broker, "status", return_value={
            "channels": {
                "email": {"configured": True, "transport": "gmail-api"},
                "push": {"configured": True},
            },
            "resilience": {"circuitsOpen": 0, "permanentFailures": 2},
        })
        result = self._run_with(patches)
        broker = next(item for item in result["components"] if item["id"] == "notification_broker")
        self.assertEqual(broker["state"], "degraded")
        self.assertEqual(broker["metrics"]["permanentFailures"], 2)
        self.assertIn("permanent", broker["detail"])
        self.assertFalse(result["launchReady"])
        self.assertIn("notification_broker", result["criticalBlockers"])
        self.assertEqual(broker["remediation"]["code"], "restore_notification_broker")


    def test_acknowledged_permanent_history_does_not_degrade_broker(self):
        patches = healthy_patches()
        patches[1] = mock.patch.object(readiness.notification_broker, "status", return_value={
            "channels": {
                "email": {"configured": True, "transport": "gmail-api"},
                "push": {"configured": True},
            },
            "resilience": {
                "circuitsOpen": 0,
                "permanentFailures": 0,
                "permanentFailureHistory": 2,
                "permanentAcknowledged": 2,
                "permanentResolved": 0,
            },
        })
        result = self._run_with(patches)
        broker = next(item for item in result["components"] if item["id"] == "notification_broker")
        self.assertEqual(broker["state"], "ready")
        self.assertEqual(broker["metrics"]["permanentFailures"], 0)
        self.assertEqual(broker["metrics"]["permanentFailureHistory"], 2)
        self.assertEqual(broker["metrics"]["permanentAcknowledged"], 2)
        self.assertIn("acquitt", broker["detail"])
        self.assertNotIn("notification_broker", result["criticalBlockers"])


    def test_configured_email_with_failed_preflight_blocks_activation(self):
        patches = healthy_patches()
        patches[2] = mock.patch.object(readiness.notification_preflight, "run", return_value={
            "email": {"ok": False, "state": "transport_unavailable"},
            "push": {"ready": True, "state": "ready", "keyValid": True},
        })
        result = self._run_with(patches)
        states = {item["id"]: item["state"] for item in result["components"]}
        self.assertEqual(states["email_delivery"], "degraded")
        self.assertFalse(result["activationGate"]["allowed"])
        self.assertIn("email_delivery", result["criticalBlockers"])
        email = next(item for item in result["components"] if item["id"] == "email_delivery")
        self.assertEqual(email["metrics"]["preflightState"], "transport_unavailable")

    def test_review_followup_is_degraded_when_mail_preflight_is_not_ready(self):
        patches = healthy_patches()
        patches[10] = mock.patch.object(readiness.review_followup, "status", return_value={
            "emailTransportConfigured": True,
            "emailTransportReady": False,
            "emailPreflightState": "awaiting_credentials",
            "reviewUrlConfigured": True,
            "sentTotal": 0,
        })
        result = self._run_with(patches)
        review = next(item for item in result["components"] if item["id"] == "review_followup")
        self.assertEqual(review["state"], "degraded")
        self.assertEqual(review["metrics"]["emailPreflightState"], "awaiting_credentials")
        self.assertTrue(result["activationGate"]["allowed"])



    def test_ios_release_preflight_surfaces_repository_mismatch(self):
        patches = healthy_patches()
        patches[-1] = mock.patch.object(readiness.ios_release_preflight, "status", return_value={
            "state": "degraded", "projectReady": False, "associationReady": True,
            "publicationReady": False, "channel": "pending",
            "checks": [
                {"code": "release_apns_environment", "ok": False},
                {"code": "bundle_identifier", "ok": True},
            ],
        })
        result = self._run_with(patches)
        release = next(item for item in result["components"] if item["id"] == "ios_release_preflight")
        self.assertEqual(release["state"], "degraded")
        self.assertEqual(release["metrics"]["failedChecks"], ["release_apns_environment"])
        self.assertFalse(release["critical"])
        self.assertTrue(result["activationGate"]["allowed"])

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


    def test_referral_integrity_anomalies_are_visible_without_blocking_core_launch(self):
        patches = healthy_patches()
        patches.append(mock.patch.object(readiness.referral_integrity_audit, "status", return_value={
            "ok": False,
            "state": "degraded",
            "issues": 4,
            "metrics": {
                "accountsInDebt": 1,
                "ambiguousLegacyReferences": 1,
                "missingEarns": 1,
                "orphanEarns": 0,
                "amountMismatches": 1,
                "missingReversals": 1,
                "orphanReversals": 0,
            },
        }))
        result = self._run_with(patches)
        referrals = next(item for item in result["components"] if item["id"] == "referrals")
        self.assertEqual(referrals["state"], "degraded")
        self.assertEqual(referrals["metrics"]["integrityIssues"], 4)
        self.assertEqual(referrals["metrics"]["accountsInDebt"], 1)
        self.assertEqual(referrals["metrics"]["ambiguousLegacyReferences"], 1)
        self.assertEqual(referrals["remediation"]["code"], "restore_referrals")
        self.assertTrue(result["activationGate"]["allowed"])

    def test_referral_integrity_probe_failure_is_bounded(self):
        patches = healthy_patches()
        patches.append(mock.patch.object(
            readiness.referral_integrity_audit,
            "status",
            side_effect=readiness.referral_integrity_audit.ReferralAuditUnavailable("private-customer-token"),
        ))
        result = self._run_with(patches)
        referrals = next(item for item in result["components"] if item["id"] == "referrals")
        self.assertEqual(referrals["state"], "degraded")
        encoded = json.dumps(result, sort_keys=True)
        self.assertNotIn("private-customer-token", encoded)
        self.assertIn("ReferralAuditUnavailable", encoded)


if __name__ == "__main__":
    unittest.main()
