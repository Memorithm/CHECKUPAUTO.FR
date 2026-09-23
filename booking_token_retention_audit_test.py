import datetime
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import analytics_store
import booking_bridge
import compliance_store
import retention_enforcement as retention


class BookingTokenRetentionAuditTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.old_env = {
            key: os.environ.get(key)
            for key in ("CYBERCHECK_DATA_DIR", "CYBERCHECK_PRIVATE_DIR")
        }
        os.environ["CYBERCHECK_DATA_DIR"] = str(self.root)
        os.environ["CYBERCHECK_PRIVATE_DIR"] = str(self.root / "private")
        self.addCleanup(self._restore_env)

        self.old_analytics_db = analytics_store.DB
        self.old_booking_secret = booking_bridge.SECRET_FILE
        analytics_store.DB = self.root / "analytics.sqlite3"
        booking_bridge.SECRET_FILE = self.root / "private" / "mercure-webhook-secret"
        self.addCleanup(self._restore_globals)

        self.compliance_db = self.root / "compliance.sqlite3"
        compliance_store.init_db(self.compliance_db)
        retention.init_db(self.compliance_db)
        booking_bridge.init_db()
        self.now = datetime.datetime(2026, 9, 23, 20, 0, tzinfo=datetime.timezone.utc)

    def _restore_env(self):
        for key, value in self.old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _restore_globals(self):
        analytics_store.DB = self.old_analytics_db
        booking_bridge.SECRET_FILE = self.old_booking_secret

    def _insert_intent(self, token: str, age_hours: int) -> str:
        key = booking_bridge._attribution_key(token)
        created = (self.now - datetime.timedelta(hours=age_hours)).isoformat(timespec="seconds")
        with analytics_store.connect() as db:
            db.execute(
                """INSERT INTO booking_intents(
                     token,attribution_key,created_at,source,campaign,device,path,service
                   ) VALUES(?,?,?,?,?,?,?,?)""",
                (token, key, created, "Direct", "", "desktop", "/", ""),
            )
        return key

    def _run(self, *, dry_run: bool):
        with mock.patch.object(retention, "_now", return_value=self.now), mock.patch.object(
            retention.site_config_store,
            "load",
            return_value={"analytics": {"retentionDays": 30}},
        ):
            return retention.run_once(dry_run=dry_run, db_path=self.compliance_db)

    def test_expired_browser_token_is_retired_with_minimized_audit_evidence(self):
        expired_token = "browser-secret-expired"
        fresh_token = "browser-secret-fresh"
        expired_key = self._insert_intent(expired_token, 49)
        self._insert_intent(fresh_token, 47)

        result = self._run(dry_run=False)
        row = next(item for item in result["rules"] if item["ruleId"] == "booking_browser_tokens")
        self.assertEqual(row["state"], "ready")
        self.assertEqual(row["removedCount"], 1)
        self.assertEqual(row["audit"]["cutoffAt"], "2026-09-21T20:00:00+00:00")
        self.assertEqual(row["audit"]["mode"], "purge")
        self.assertTrue(row["audit"]["auditId"])

        with analytics_store.connect() as db:
            tokens = {str(item["token"]) for item in db.execute("SELECT token FROM booking_intents")}
        self.assertIn(expired_key, tokens)
        self.assertIn(fresh_token, tokens)
        self.assertNotIn(expired_token, tokens)

        evidence = {
            "runId": result["runId"],
            "ruleId": "booking_browser_tokens",
            "mode": "purge",
            "removedCount": 1,
            "cutoffAt": "2026-09-21T20:00:00+00:00",
        }
        expected_hash = hashlib.sha256(
            json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        self.assertEqual(row["audit"]["evidenceHash"], expected_hash)
        audits = retention.audit_rows(self.compliance_db)
        audit = next(item for item in audits if item["ruleId"] == "booking_browser_tokens")
        self.assertEqual(audit["evidenceHash"], expected_hash)
        self.assertNotIn(expired_token, repr(audits))
        self.assertNotIn(fresh_token, repr(audits))

    def test_dry_run_records_cutoff_without_retiring_token(self):
        token = "browser-secret-dry-run"
        self._insert_intent(token, 49)

        result = self._run(dry_run=True)
        row = next(item for item in result["rules"] if item["ruleId"] == "booking_browser_tokens")
        self.assertEqual(row["removedCount"], 1)
        self.assertEqual(row["audit"]["mode"], "dry_run")
        self.assertEqual(row["audit"]["cutoffAt"], "2026-09-21T20:00:00+00:00")
        with analytics_store.connect() as db:
            stored = db.execute(
                "SELECT token FROM booking_intents WHERE token=?", (token,)
            ).fetchone()
        self.assertIsNotNone(stored)

    def test_policy_exposes_fixed_checkout_lifetime_without_site_configuration(self):
        state = retention.policy("booking_browser_tokens", self.compliance_db)
        self.assertTrue(state["ready"])
        self.assertTrue(state["configured"])
        self.assertEqual(state["mode"], "fixed_duration")
        self.assertEqual(state["activeHours"], booking_bridge.BOOKING_BROWSER_TOKEN_TTL_HOURS)
        self.assertEqual(state["activeHours"], 48)


if __name__ == "__main__":
    unittest.main()
