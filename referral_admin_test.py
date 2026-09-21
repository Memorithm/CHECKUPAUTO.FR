import json
import unittest
from unittest import mock

import referral_admin


class ReferralAdminTest(unittest.TestCase):
    def test_status_combines_accounts_reward_and_integrity(self):
        report = {
            "ok": False,
            "state": "degraded",
            "issues": 2,
            "metrics": {"accountsInDebt": 1, "missingEarns": 1},
        }
        with mock.patch.object(referral_admin.referrals, "list_accounts", return_value=[{"code": "ABC123"}]) as accounts, \
             mock.patch.object(referral_admin.referrals, "configured_reward_cents", return_value=500), \
             mock.patch.object(referral_admin.integrity_audit, "status", return_value=report):
            result = referral_admin.status(1000)
        accounts.assert_called_once_with(500)
        self.assertTrue(result["ok"])
        self.assertEqual(result["rewardCents"], 500)
        self.assertEqual(result["integrity"], report)

    def test_known_audit_unavailability_is_bounded(self):
        marker = "customer-private-marker"
        with mock.patch.object(referral_admin.referrals, "list_accounts", return_value=[]), \
             mock.patch.object(referral_admin.referrals, "configured_reward_cents", return_value=500), \
             mock.patch.object(
                 referral_admin.integrity_audit,
                 "status",
                 side_effect=referral_admin.integrity_audit.ReferralAuditUnavailable(marker),
             ):
            result = referral_admin.status(10)
        encoded = json.dumps(result, sort_keys=True)
        self.assertNotIn(marker, encoded)
        self.assertEqual(result["integrity"]["state"], "unavailable")
        self.assertEqual(result["integrity"]["error"], "referral_ledger_unavailable")

    def test_unexpected_audit_failure_exposes_type_not_message(self):
        marker = "private-referral-marker"
        with mock.patch.object(referral_admin.referrals, "list_accounts", return_value=[]), \
             mock.patch.object(referral_admin.referrals, "configured_reward_cents", return_value=500), \
             mock.patch.object(referral_admin.integrity_audit, "status", side_effect=RuntimeError(marker)):
            result = referral_admin.status(10)
        encoded = json.dumps(result, sort_keys=True)
        self.assertNotIn(marker, encoded)
        self.assertEqual(result["integrity"]["error"], "RuntimeError")

    def test_limit_is_bounded_and_never_zero(self):
        with mock.patch.object(referral_admin.referrals, "list_accounts", return_value=[]) as accounts, \
             mock.patch.object(referral_admin.referrals, "configured_reward_cents", return_value=500), \
             mock.patch.object(referral_admin.integrity_audit, "status", return_value={"ok": True, "state": "ready", "issues": 0, "metrics": {}}):
            referral_admin.status(0)
        accounts.assert_called_once_with(1)


if __name__ == "__main__":
    unittest.main()
