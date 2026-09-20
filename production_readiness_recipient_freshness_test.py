import unittest
from unittest import mock

import production_readiness as readiness
from production_readiness_test import CONFIG, SEO_READY, healthy_patches


class RecipientReconciliationReadinessTest(unittest.TestCase):
    def _report(self, resilience):
        patchers = healthy_patches()
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        broker = {
            "channels": {
                "email": {"configured": True, "transport": "gmail-api"},
                "push": {"configured": True},
            },
            "resilience": resilience,
        }
        with mock.patch.object(readiness.notification_broker, "status", return_value=broker):
            return readiness.status(CONFIG, SEO_READY)

    def test_fresh_checks_keep_acknowledged_history_ready(self):
        report = self._report({
            "circuitsOpen": 0,
            "permanentFailures": 0,
            "permanentFailureHistory": 1,
            "permanentAcknowledged": 1,
            "permanentResolved": 0,
            "recipientChecks": {
                "tracked": 1,
                "fresh": 1,
                "stale": 0,
                "unchecked": 0,
                "changed": 0,
                "unchanged": 1,
                "missing": 0,
                "lookupFailed": 0,
                "staleAfterSeconds": 7200,
            },
        })
        broker = next(item for item in report["components"] if item["id"] == "notification_broker")
        self.assertEqual(broker["state"], "ready")
        self.assertEqual(broker["metrics"]["recipientChecksFresh"], 1)
        self.assertEqual(broker["metrics"]["recipientChecksStale"], 0)
        self.assertTrue(report["activationGate"]["allowed"])

    def test_stale_checks_degrade_broker_even_without_open_failure(self):
        report = self._report({
            "circuitsOpen": 0,
            "permanentFailures": 0,
            "permanentFailureHistory": 1,
            "permanentAcknowledged": 1,
            "permanentResolved": 0,
            "recipientChecks": {
                "tracked": 1,
                "fresh": 0,
                "stale": 1,
                "unchecked": 0,
                "changed": 0,
                "unchanged": 1,
                "missing": 0,
                "lookupFailed": 0,
                "staleAfterSeconds": 7200,
            },
        })
        broker = next(item for item in report["components"] if item["id"] == "notification_broker")
        self.assertEqual(broker["state"], "degraded")
        self.assertEqual(broker["metrics"]["recipientChecksStale"], 1)
        self.assertIn("périmé", broker["detail"])
        self.assertIn("notification_broker", report["criticalBlockers"])
        self.assertFalse(report["activationGate"]["allowed"])

    def test_fresh_lookup_failure_degrades_broker(self):
        report = self._report({
            "circuitsOpen": 0,
            "permanentFailures": 0,
            "permanentFailureHistory": 1,
            "permanentAcknowledged": 1,
            "permanentResolved": 0,
            "recipientChecks": {
                "tracked": 1,
                "fresh": 1,
                "stale": 0,
                "unchecked": 0,
                "changed": 0,
                "unchanged": 0,
                "missing": 0,
                "lookupFailed": 1,
                "staleAfterSeconds": 7200,
            },
        })
        broker = next(item for item in report["components"] if item["id"] == "notification_broker")
        self.assertEqual(broker["state"], "degraded")
        self.assertEqual(broker["metrics"]["recipientLookupFailed"], 1)
        self.assertIn("Mercure", broker["detail"])
        self.assertIn("notification_broker", report["criticalBlockers"])


if __name__ == "__main__":
    unittest.main()
