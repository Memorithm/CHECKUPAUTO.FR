import io
import json
import tempfile
import unittest
from pathlib import Path

import analytics_store as analytics
import referral_engine as referrals
import referral_wallet_claim_cli as cli


class ReferralWalletClaimCliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = analytics.DB
        analytics.DB = Path(self.tmp.name) / "analytics.sqlite3"
        analytics.init_db()
        referrals.init_db()
        self.account = referrals.create_account("CLAIM-7K4P")

    def tearDown(self):
        analytics.DB = self.old_db
        self.tmp.cleanup()

    def test_issue_reads_json_from_stdin_and_returns_one_time_secret(self):
        stdout = io.StringIO()
        code = cli.main(
            ["issue"],
            stdin=io.StringIO(json.dumps({"code": self.account["code"], "ttlSeconds": 600})),
            stdout=stdout,
        )
        self.assertEqual(code, 0)
        result = json.loads(stdout.getvalue())
        self.assertTrue(result["ok"])
        self.assertTrue(result["claim"]["singleUse"])
        self.assertFalse(result["claim"]["rawTokenPersisted"])
        self.assertGreaterEqual(len(result["claim"]["claimToken"]), 32)

    def test_status_is_aggregate_only(self):
        stdout = io.StringIO()
        code = cli.main(["status"], stdin=io.StringIO(), stdout=stdout)
        self.assertEqual(code, 0)
        result = json.loads(stdout.getvalue())
        self.assertTrue(result["ok"])
        rendered = stdout.getvalue()
        self.assertNotIn(self.account["id"], rendered)
        self.assertNotIn(self.account["code"], rendered)

    def test_invalid_account_error_is_sanitized(self):
        stdout = io.StringIO()
        code = cli.main(
            ["issue"],
            stdin=io.StringIO(json.dumps({"code": "MISSING-7K4P"})),
            stdout=stdout,
        )
        self.assertEqual(code, 2)
        self.assertEqual(
            json.loads(stdout.getvalue()),
            {"ok": False, "error": "invalid_or_unauthorized_request"},
        )
        self.assertNotIn("MISSING-7K4P", stdout.getvalue())

    def test_payload_is_bounded(self):
        stdout = io.StringIO()
        code = cli.main(
            ["issue"],
            stdin=io.StringIO(json.dumps({"code": "A" * (cli.MAX_STDIN_BYTES + 10)})),
            stdout=stdout,
        )
        self.assertEqual(code, 2)
        self.assertEqual(
            json.loads(stdout.getvalue()),
            {"ok": False, "error": "invalid_or_unauthorized_request"},
        )


if __name__ == "__main__":
    unittest.main()
