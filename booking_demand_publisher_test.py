"""RemoteOps canary contract without accessing Mercure or private stores."""
import datetime as dt
import json
import unittest
from unittest.mock import patch

import booking_demand as demand
from scripts import booking_demand_publish as cli


class RemoteOpsPublisherCLITest(unittest.TestCase):
    @patch.object(cli.site_config_store, "load",
                  return_value={"incentives": {"enabled": True}})
    @patch.object(demand, "run_once",
                  return_value={"status": "verified", "published": 1})
    def test_canary_limits_impact_to_one_slot(self, publisher, _config):
        self.assertEqual(cli.execute("canary")["published"], 1)
        publisher.assert_called_once_with(
            {"enabled": True}, max_new_promotions=1)

    @patch.object(cli.site_config_store, "load",
                  return_value={"incentives": {"enabled": True}})
    @patch.object(demand, "run_once",
                  return_value={"status": "no_new_offers", "published": 0})
    def test_routine_is_bounded_by_engine_limit(self, publisher, _config):
        self.assertEqual(cli.execute("routine")["status"], "no_new_offers")
        publisher.assert_called_once_with(
            {"enabled": True},
            max_new_promotions=demand.MAX_NEW_PROMOTIONS_PER_RUN)

    def test_unverified_provider_write_fails_the_job(self):
        with patch.object(cli, "execute",
                          return_value={"status": "unverified", "published": 0}), \
             patch("builtins.print"):
            self.assertEqual(cli.main(["--mode", "canary"]), 2)

    def test_unavailable_provider_does_not_expose_secrets(self):
        with patch.object(cli, "execute",
                          side_effect=RuntimeError("secret=PRIVATE-TOKEN")), \
             patch("builtins.print") as output:
            self.assertEqual(cli.main(["--mode", "canary"]), 2)
        text = output.call_args.args[0]
        self.assertNotIn("PRIVATE-TOKEN", text)
        self.assertEqual(json.loads(text)["errorType"], "RuntimeError")

    def test_diagnose_is_readonly_and_returns_aggregate_only(self):
        history = {
            "totals": {1: 35}, "counts": {(1, 10): 30, (1, 15): 5},
            "peaks": {1: 30}, "historyDays": 84,
        }
        with patch.object(cli.site_config_store, "load", return_value={
            "incentives": {"eligibleServices": {
                "technical": True, "fitted": False
            }}
        }), patch.object(cli.mercure_admin_client, "business_today",
                         return_value=dt.date(2026, 10, 8)), \
             patch.object(demand, "snapshot", return_value=history), \
             patch.object(cli.mercure_public_client, "availability",
                          return_value={"days": []}), \
             patch.object(demand, "run_once") as publisher:
            result = cli.execute("diagnose")
        publisher.assert_not_called()
        self.assertEqual(result["aggregatedAppointments"], 35)
        self.assertEqual(result["candidateCount"], 0)

    def test_unknown_mode_is_rejected(self):
        with patch.object(cli.site_config_store, "load",
                          return_value={"incentives": {}}):
            with self.assertRaises(ValueError):
                cli.execute("any")


if __name__ == "__main__":
    unittest.main()
