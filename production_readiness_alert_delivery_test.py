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
