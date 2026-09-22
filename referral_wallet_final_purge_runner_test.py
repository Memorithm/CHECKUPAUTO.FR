import unittest
from unittest import mock

import referral_wallet_final_purge_runner as runner


class ReferralWalletFinalPurgeRunnerTest(unittest.TestCase):
    def test_unconfigured_policy_is_reported_as_blocked_without_failure(self):
        with mock.patch.object(
            runner.retention_enforcement,
            "policy",
            return_value={"ready": False, "blocker": "policy_configuration_required"},
        ), mock.patch.object(runner.referral_wallet_final_purge, "purge_retired_wallets") as purge:
            result = runner.process_once()

        self.assertTrue(result["ok"])
        self.assertEqual(result["state"], "blocked")
        self.assertEqual(result["reason"], "policy_configuration_required")
        self.assertEqual(result["purgedRows"], 0)
        purge.assert_not_called()

    def test_legal_review_is_checked_even_if_policy_claims_ready(self):
        with mock.patch.object(
            runner.retention_enforcement,
            "policy",
            return_value={"ready": True, "activeDays": 30, "legalReviewConfirmed": False},
        ), mock.patch.object(runner.referral_wallet_final_purge, "purge_retired_wallets") as purge:
            result = runner.process_once()

        self.assertEqual(result["state"], "blocked")
        self.assertEqual(result["reason"], "legal_review_required")
        purge.assert_not_called()

    def test_ready_policy_delegates_exact_reviewed_duration(self):
        with mock.patch.object(
            runner.retention_enforcement,
            "policy",
            return_value={"ready": True, "activeDays": 365, "legalReviewConfirmed": True},
        ), mock.patch.object(
            runner.referral_wallet_final_purge,
            "purge_retired_wallets",
            return_value={
                "ok": True,
                "dryRun": True,
                "eligibleAccounts": 2,
                "purgedAccounts": 0,
                "purgedRows": 0,
                "recoveredPlannedOperations": 0,
                "evidenceHash": "a" * 64,
                "rawAccountIdentifiersPersisted": False,
            },
        ) as purge:
            result = runner.process_once(dry_run=True, db_path="/tmp/compliance.sqlite3")

        purge.assert_called_once_with(
            365,
            dry_run=True,
            db_path="/tmp/compliance.sqlite3",
        )
        self.assertEqual(result["state"], "ready")
        self.assertEqual(result["retentionDays"], 365)
        self.assertTrue(result["legalReviewConfirmed"])
        self.assertEqual(result["eligibleAccounts"], 2)

    def test_unconfirmed_purge_result_fails_closed(self):
        with mock.patch.object(
            runner.retention_enforcement,
            "policy",
            return_value={"ready": True, "activeDays": 30, "legalReviewConfirmed": True},
        ), mock.patch.object(
            runner.referral_wallet_final_purge,
            "purge_retired_wallets",
            return_value={"ok": False},
        ):
            with self.assertRaisesRegex(RuntimeError, "non confirmée"):
                runner.process_once()


if __name__ == "__main__":
    unittest.main()
