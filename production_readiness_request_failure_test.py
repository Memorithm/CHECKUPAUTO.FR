import unittest
from unittest import mock

import production_readiness as readiness
from production_readiness_test import CONFIG, SEO_READY, healthy_patches


class ProductionReadinessRequestFailureTest(unittest.TestCase):
    def test_active_request_failure_degrades_critical_notification_broker(self):
        patches = healthy_patches()
        patches[1] = mock.patch.object(readiness.notification_broker, "status", return_value={
            "channels": {
                "email": {"configured": True, "transport": "gmail-api"},
                "push": {"configured": True},
            },
            "failureCounts": {"request": 2},
            "resilience": {
                "circuitsOpen": 0,
                "permanentFailures": 0,
                "recipientChecks": {"tracked": 0, "fresh": 0, "stale": 0, "unchecked": 0, "lookupFailed": 0},
            },
        })
        started = []
        try:
            for patcher in patches:
                patcher.start()
                started.append(patcher)
            result = readiness.status(CONFIG, SEO_READY)
        finally:
            for patcher in reversed(started):
                patcher.stop()

        broker = next(item for item in result["components"] if item["id"] == "notification_broker")
        self.assertEqual(broker["state"], "degraded")
        self.assertEqual(broker["metrics"]["requestFailures"], 2)
        self.assertIn("requête non retentable", broker["detail"])
        self.assertFalse(result["activationGate"]["allowed"])
        self.assertIn("notification_broker", result["criticalBlockers"])
        self.assertEqual(broker["remediation"]["code"], "restore_notification_broker")


if __name__ == "__main__":
    unittest.main()
