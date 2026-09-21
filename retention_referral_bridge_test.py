import unittest
from unittest import mock

import retention_enforcement


class ReferralRetentionBridgeTest(unittest.TestCase):
    def test_referral_rule_has_an_executable_purger(self):
        rule = retention_enforcement.CONFIGURABLE_RULES["referral_ledger"]
        self.assertNotIn("implementationRequired", rule)

    def test_configurable_rule_delegates_to_balance_preserving_compaction(self):
        result = {
            "ok": True,
            "dryRun": True,
            "compactedEntries": 7,
            "skippedEntries": 0,
            "netCents": 1250,
            "evidenceHash": "a" * 64,
        }
        with mock.patch.object(
            retention_enforcement.referral_engine,
            "compact_ledger",
            return_value=result,
        ) as compact:
            removed = retention_enforcement._run_configurable_rule(
                {"id": "referral_ledger", "activeDays": 1095},
                dry_run=True,
                db_path=None,
            )

        self.assertEqual(removed, 7)
        compact.assert_called_once_with(1095, dry_run=True)

    def test_skipped_historical_entries_fail_closed(self):
        result = {
            "ok": True,
            "compactedEntries": 4,
            "skippedEntries": 1,
            "netCents": 0,
        }
        with mock.patch.object(
            retention_enforcement.referral_engine,
            "compact_ledger",
            return_value=result,
        ):
            with self.assertRaisesRegex(RuntimeError, "incomplète"):
                retention_enforcement._compact_referral_ledger(1095, dry_run=False)

    def test_unconfirmed_compaction_fails_closed(self):
        with mock.patch.object(
            retention_enforcement.referral_engine,
            "compact_ledger",
            return_value={"ok": False, "compactedEntries": 0, "skippedEntries": 0},
        ):
            with self.assertRaisesRegex(RuntimeError, "non confirmée"):
                retention_enforcement._compact_referral_ledger(1095, dry_run=False)

    def test_negative_compaction_count_is_rejected(self):
        with mock.patch.object(
            retention_enforcement.referral_engine,
            "compact_ledger",
            return_value={"ok": True, "compactedEntries": -1, "skippedEntries": 0},
        ):
            with self.assertRaisesRegex(RuntimeError, "incohérente"):
                retention_enforcement._compact_referral_ledger(1095, dry_run=False)


if __name__ == "__main__":
    unittest.main()
