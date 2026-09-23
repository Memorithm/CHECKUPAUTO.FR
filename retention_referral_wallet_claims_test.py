import datetime
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import analytics_store
import referral_engine
import referral_wallet_claims
import retention_enforcement as retention


class ReferralWalletClaimRetentionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.old_db = analytics_store.DB
        analytics_store.DB = self.root / "analytics.sqlite3"
        self.addCleanup(self._restore)
        self.compliance_db = self.root / "compliance.sqlite3"

    def _restore(self):
        analytics_store.DB = self.old_db

    @staticmethod
    def _past() -> str:
        return (
            datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(minutes=5)
        ).isoformat(timespec="seconds")

    def _seed_claims(self):
        referral_engine.create_account("CA-OLD1")
        referral_engine.create_account("CA-LIVE1")
        old = referral_wallet_claims.issue("CA-OLD1", 600)
        live = referral_wallet_claims.issue("CA-LIVE1", 600)
        old_hash = hashlib.sha256(old["claimToken"].encode("utf-8")).hexdigest()
        live_hash = hashlib.sha256(live["claimToken"].encode("utf-8")).hexdigest()
        with analytics_store.connect() as db:
            db.execute(
                "UPDATE referral_wallet_claim SET expires_at=? WHERE token_hash=?",
                (self._past(), old_hash),
            )
        return old, live, old_hash, live_hash

    def test_expired_wallet_claims_are_dry_run_counted_then_physically_purged(self):
        old, live, old_hash, live_hash = self._seed_claims()

        self.assertEqual(retention._purge_referral_wallet_claims(dry_run=True), 1)
        with analytics_store.connect() as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) n FROM referral_wallet_claim").fetchone()["n"],
                2,
            )

        with (
            mock.patch.object(retention.site_config_store, "load", return_value={"analytics": {"retentionDays": 30}}),
            mock.patch.object(retention, "_purge_analytics", return_value=0),
            mock.patch.object(retention, "_retire_booking_browser_tokens", return_value=0),
            mock.patch.object(retention, "_purge_booking_intents", return_value=0),
            mock.patch.object(retention, "_purge_mobile_claims", return_value=0),
            mock.patch.object(retention, "_purge_inactive_suppressions", return_value=0),
        ):
            result = retention.run_once(dry_run=False, db_path=self.compliance_db)

        row = next(item for item in result["rules"] if item["ruleId"] == "referral_wallet_claims")
        self.assertEqual(row["state"], "ready")
        self.assertEqual(row["removedCount"], 1)
        with analytics_store.connect() as db:
            rows = db.execute(
                "SELECT token_hash FROM referral_wallet_claim ORDER BY token_hash"
            ).fetchall()
        self.assertEqual([item["token_hash"] for item in rows], [live_hash])

        audit = next(
            item for item in retention.audit_rows(self.compliance_db)
            if item["ruleId"] == "referral_wallet_claims"
        )
        self.assertEqual(len(audit["evidenceHash"]), 64)
        evidence = repr(audit)
        self.assertNotIn(old["claimToken"], evidence)
        self.assertNotIn(live["claimToken"], evidence)
        self.assertNotIn(old_hash, evidence)
        self.assertNotIn(live_hash, evidence)

    def test_rule_is_event_driven_and_requires_no_arbitrary_duration(self):
        state = retention.policy("referral_wallet_claims", self.compliance_db)
        self.assertTrue(state["ready"])
        self.assertEqual(state["mode"], "event")
        self.assertNotIn("activeDays", state)


if __name__ == "__main__":
    unittest.main()
