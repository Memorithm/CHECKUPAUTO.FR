import io
import json
import tempfile
import unittest
from pathlib import Path

import analytics_store as analytics
import mobile_devices as devices
import referral_engine as referrals
import referral_wallet_claim_cli as cli


class ReferralWalletClaimCliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = analytics.DB
        self.old_mobile_dir, self.old_mobile_db = devices.DATA_DIR, devices.DB
        analytics.DB = Path(self.tmp.name) / "analytics.sqlite3"
        devices.DATA_DIR = Path(self.tmp.name) / "mobile"
        devices.DB = devices.DATA_DIR / "devices.sqlite3"
        analytics.init_db()
        referrals.init_db()
        devices.init_db()
        self.account = referrals.create_account("CLAIM-7K4P")
        self.installation = "60cf7ccf-4297-41f4-b76b-c0bd44dbe3d1"
        self.secret = "A" * 43
        devices.register_installation({
            "installationId": self.installation,
            "registrationSecret": self.secret,
        })

    def tearDown(self):
        analytics.DB = self.old_db
        devices.DATA_DIR, devices.DB = self.old_mobile_dir, self.old_mobile_db
        self.tmp.cleanup()

    def _issue(self) -> dict:
        stdout = io.StringIO()
        code = cli.main(
            ["issue"],
            stdin=io.StringIO(json.dumps({"code": self.account["code"], "ttlSeconds": 600})),
            stdout=stdout,
        )
        self.assertEqual(code, 0)
        return json.loads(stdout.getvalue())["claim"]

    def test_issue_reads_json_from_stdin_and_returns_one_time_secret(self):
        claim = self._issue()
        self.assertTrue(claim["singleUse"])
        self.assertFalse(claim["rawTokenPersisted"])
        self.assertEqual(claim["claimType"], "referral_wallet")
        self.assertTrue(claim["claimToken"].startswith("rw_"))
        self.assertGreaterEqual(len(claim["claimToken"]), 35)

    def test_consume_accepts_only_stdin_credentials_and_projects_evidence(self):
        claim = self._issue()
        stdout = io.StringIO()
        code = cli.main(
            ["consume"],
            stdin=io.StringIO(json.dumps({
                "installationId": self.installation,
                "registrationSecret": self.secret,
                "claimToken": claim["claimToken"],
            })),
            stdout=stdout,
        )
        self.assertEqual(code, 0)
        result = json.loads(stdout.getvalue())
        self.assertTrue(result["ok"])
        self.assertEqual(result["claimType"], "referral_wallet")
        self.assertEqual(result["provenance"], "authenticated_mobile_wallet_claim")
        self.assertFalse(result["rawInstallationPersisted"])
        self.assertFalse(result["rawClaimTokenPersisted"])
        rendered = stdout.getvalue()
        self.assertNotIn(self.account["id"], rendered)
        self.assertNotIn(self.installation, rendered)
        self.assertNotIn(self.secret, rendered)
        self.assertNotIn(claim["claimToken"], rendered)

    def test_consume_rejects_extra_fields_and_sanitizes_error(self):
        claim = self._issue()
        stdout = io.StringIO()
        code = cli.main(
            ["consume"],
            stdin=io.StringIO(json.dumps({
                "installationId": self.installation,
                "registrationSecret": self.secret,
                "claimToken": claim["claimToken"],
                "accountId": self.account["id"],
            })),
            stdout=stdout,
        )
        self.assertEqual(code, 2)
        self.assertEqual(
            json.loads(stdout.getvalue()),
            {"ok": False, "error": "invalid_or_unauthorized_request"},
        )
        self.assertNotIn(self.account["id"], stdout.getvalue())

    def test_status_is_aggregate_only(self):
        stdout = io.StringIO()
        code = cli.main(["status"], stdin=io.StringIO(), stdout=stdout)
        self.assertEqual(code, 0)
        result = json.loads(stdout.getvalue())
        self.assertTrue(result["ok"])
        self.assertEqual(result["capability"]["claimTokenPrefix"], "rw_")
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
