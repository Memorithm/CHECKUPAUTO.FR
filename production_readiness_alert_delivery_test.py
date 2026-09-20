import unittest
from unittest import mock

import production_readiness as readiness
from production_readiness_test import CONFIG, SEO_READY, healthy_patches


class ProductionReadinessAlertDeliveryTest(unittest.TestCase):
    def _run_with_alerts(self, alert_summary):
        patches = healthy_patches()
        patches[-1] = mock.patch.object(
            readiness.security_alerts, "summary", return_value=alert_summary
        )
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        result = readiness.status(CONFIG, SEO_READY)
        return next(item for item in result["components"] if item["id"] == "alert_delivery")

    def test_missing_relay_is_configuration_required_even_without_pending_alerts(self):
        component = self._run_with_alerts({
            "open": 0,
            "undeliveredHighOrCritical": 0,
            "delivery": {"configured": False, "ready": False, "state": "awaiting_webhook", "signed": False},
        })
        self.assertEqual(component["state"], "configuration_required")
        self.assertEqual(component["metrics"]["deliveryState"], "awaiting_webhook")

    def test_ready_relay_with_pending_retry_is_degraded_and_observable(self):
        component = self._run_with_alerts({
            "open": 2,
            "undeliveredHighOrCritical": 2,
            "delivery": {
                "configured": True,
                "ready": True,
                "state": "ready",
                "signed": True,
                "retry": {
                    "eligible": 1,
                    "deferred": 1,
                    "lastFailure": {
                        "at": "2026-09-20T04:00:00+00:00",
                        "reason": "timeout",
                        "nextAttemptAt": "2026-09-20T04:01:00+00:00",
                    },
                },
            },
        })
        self.assertEqual(component["state"], "degraded")
        self.assertEqual(component["metrics"]["retryEligible"], 1)
        self.assertEqual(component["metrics"]["retryDeferred"], 1)
        self.assertEqual(component["metrics"]["lastFailureReason"], "timeout")
        self.assertEqual(component["metrics"]["nextAttemptAt"], "2026-09-20T04:01:00+00:00")

    def test_ready_relay_without_pending_alerts_is_ready(self):
        component = self._run_with_alerts({
            "open": 0,
            "undeliveredHighOrCritical": 0,
            "delivery": {
                "configured": True,
                "ready": True,
                "state": "ready",
                "signed": True,
                "retry": {"eligible": 0, "deferred": 0, "lastFailure": None},
            },
        })
        self.assertEqual(component["state"], "ready")
