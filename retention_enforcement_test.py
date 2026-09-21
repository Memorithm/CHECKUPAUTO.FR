import datetime
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import analytics_store
import booking_bridge
import compliance_store
import mobile_devices
import notification_broker
import privacy_suppression
import reminder_dispatch
import retention_enforcement as retention
import review_followup


class RetentionEnforcementTest(unittest.TestCase):
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

        import security_alerts
        import security_behavior
        import security_guard
        self.security_alerts = security_alerts
        self.security_behavior = security_behavior
        self.security_guard = security_guard

        self.originals = {
            "analytics_db": analytics_store.DB,
            "booking_secret": booking_bridge.SECRET_FILE,
            "mobile_dir": mobile_devices.DATA_DIR,
            "mobile_db": mobile_devices.DB,
            "notification_dir": notification_broker.DATA_DIR,
            "notification_db": notification_broker.DB,
            "review_dir": review_followup.DATA_DIR,
            "review_db": review_followup.DB,
            "reminder_dir": reminder_dispatch.DATA_DIR,
            "reminder_db": reminder_dispatch.DB,
            "security_guard_dir": self.security_guard.STATE_DIR,
            "security_guard_db": self.security_guard.DB,
            "security_guard_secret": self.security_guard.SECRET_FILE,
            "security_behavior_dir": self.security_behavior.STATE_DIR,
            "security_behavior_db": self.security_behavior.DB,
            "security_alerts_dir": self.security_alerts.STATE_DIR,
            "security_alerts_db": self.security_alerts.DB,
        }
        analytics_store.DB = self.root / "analytics.sqlite3"
        booking_bridge.SECRET_FILE = self.root / "private" / "mercure-webhook-secret"
        mobile_devices.DATA_DIR = self.root / "mobile"
        mobile_devices.DB = mobile_devices.DATA_DIR / "mobile.sqlite3"
        notification_broker.DATA_DIR = self.root / "notifications"
        notification_broker.DB = notification_broker.DATA_DIR / "notification.sqlite3"
        review_followup.DATA_DIR = self.root / "reviews"
        review_followup.DB = review_followup.DATA_DIR / "review.sqlite3"
        reminder_dispatch.DATA_DIR = self.root / "reminders"
        reminder_dispatch.DB = reminder_dispatch.DATA_DIR / "reminder.sqlite3"
        security_dir = self.root / "security"
        self.security_guard.STATE_DIR = security_dir
        self.security_guard.DB = security_dir / "security.sqlite3"
        self.security_guard.SECRET_FILE = security_dir / "client-hmac-secret"
        self.security_behavior.STATE_DIR = security_dir
        self.security_behavior.DB = self.security_guard.DB
        self.security_alerts.STATE_DIR = security_dir
        self.security_alerts.DB = self.security_guard.DB
        self.addCleanup(self._restore_globals)

        self.db = self.root / "compliance.sqlite3"
        compliance_store.init_db(self.db)
        retention.init_db(self.db)

    def _restore_env(self):
        for key, value in self.old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _restore_globals(self):
        analytics_store.DB = self.originals["analytics_db"]
        booking_bridge.SECRET_FILE = self.originals["booking_secret"]
        mobile_devices.DATA_DIR = self.originals["mobile_dir"]
        mobile_devices.DB = self.originals["mobile_db"]
        notification_broker.DATA_DIR = self.originals["notification_dir"]
        notification_broker.DB = self.originals["notification_db"]
        review_followup.DATA_DIR = self.originals["review_dir"]
        review_followup.DB = self.originals["review_db"]
        reminder_dispatch.DATA_DIR = self.originals["reminder_dir"]
        reminder_dispatch.DB = self.originals["reminder_db"]
        self.security_guard.STATE_DIR = self.originals["security_guard_dir"]
        self.security_guard.DB = self.originals["security_guard_db"]
        self.security_guard.SECRET_FILE = self.originals["security_guard_secret"]
        self.security_behavior.STATE_DIR = self.originals["security_behavior_dir"]
        self.security_behavior.DB = self.originals["security_behavior_db"]
        self.security_alerts.STATE_DIR = self.originals["security_alerts_dir"]
        self.security_alerts.DB = self.originals["security_alerts_db"]

    @staticmethod
    def _iso(days_ago):
        return (
            datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(days=days_ago)
        ).isoformat(timespec="seconds")

    def _site_config(self):
        return {"analytics": {"retentionDays": 30}}

    def test_auto_rules_physically_purge_only_expired_rows_and_record_hash_evidence(self):
        analytics_store.init_db()
        with analytics_store.connect() as db:
            db.execute(
                """INSERT INTO events(
                     occurred_at,event,path,source,campaign,device,referrer_host,service
                   ) VALUES(?,?,?,?,?,?,?,?)""",
                (self._iso(45), "page_view", "/", "Direct", "", "desktop", "", ""),
            )
            db.execute(
                """INSERT INTO events(
                     occurred_at,event,path,source,campaign,device,referrer_host,service
                   ) VALUES(?,?,?,?,?,?,?,?)""",
                (self._iso(2), "page_view", "/", "Direct", "", "desktop", "", ""),
            )

        booking_bridge.init_db()
        with analytics_store.connect() as db:
            db.execute(
                """INSERT INTO booking_intents(
                     token,created_at,source,campaign,device,path,service,referral_code,
                     preferred_date,preferred_time
                   ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                ("old-token", self._iso(45), "Direct", "", "desktop", "/", "", "", "", ""),
            )
            db.execute(
                """INSERT INTO booking_intents(
                     token,created_at,source,campaign,device,path,service,referral_code,
                     preferred_date,preferred_time
                   ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                ("new-token", self._iso(2), "Direct", "", "desktop", "/", "", "", "", ""),
            )

        mobile_devices.init_db()
        with mobile_devices.connect() as db:
            db.execute(
                """INSERT INTO mobile_vehicle_claim(
                     token_hash,vehicle_id,client_kind,client_id,created_at,expires_at,consumed_at
                   ) VALUES(?,?,?,?,?,?,?)""",
                ("a" * 64, "veh-old", "account", "1", self._iso(10), self._iso(1), ""),
            )
            db.execute(
                """INSERT INTO mobile_vehicle_claim(
                     token_hash,vehicle_id,client_kind,client_id,created_at,expires_at,consumed_at
                   ) VALUES(?,?,?,?,?,?,?)""",
                ("b" * 64, "veh-new", "account", "2", self._iso(1), self._iso(-1), ""),
            )

        privacy_suppression.init_db(self.db)
        with compliance_store.connect(self.db) as db:
            db.execute(
                """INSERT INTO privacy_suppression(
                     subject_kind,subject_hash,purpose,request_id,created_at,updated_at,active
                   ) VALUES(?,?,?,?,?,?,0)""",
                ("email", "c" * 64, "direct_marketing_email", "", self._iso(1200), self._iso(1200)),
            )

        with mock.patch.object(retention.site_config_store, "load", return_value=self._site_config()):
            result = retention.run_once(dry_run=False, db_path=self.db)

        by_rule = {row["ruleId"]: row for row in result["rules"]}
        self.assertEqual(by_rule["analytics_events"]["removedCount"], 1)
        self.assertEqual(by_rule["booking_intents"]["removedCount"], 1)
        self.assertEqual(by_rule["mobile_vehicle_claims"]["removedCount"], 1)
        self.assertEqual(by_rule["inactive_privacy_suppressions"]["removedCount"], 1)
        with analytics_store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) n FROM events").fetchone()["n"], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) n FROM booking_intents").fetchone()["n"], 1)
        with mobile_devices.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) n FROM mobile_vehicle_claim").fetchone()["n"], 1)
        audits = retention.audit_rows(self.db)
        self.assertGreaterEqual(len(audits), 4)
        self.assertTrue(all(len(row["evidenceHash"]) == 64 for row in audits))
        self.assertNotIn("old-token", repr(audits))
        self.assertNotIn("veh-old", repr(audits))

    def test_dry_run_counts_without_deleting(self):
        analytics_store.init_db()
        with analytics_store.connect() as db:
            db.execute(
                """INSERT INTO events(
                     occurred_at,event,path,source,campaign,device,referrer_host,service
                   ) VALUES(?,?,?,?,?,?,?,?)""",
                (self._iso(45), "page_view", "/", "Direct", "", "desktop", "", ""),
            )
        with mock.patch.object(retention.site_config_store, "load", return_value=self._site_config()):
            result = retention.run_once(dry_run=True, db_path=self.db)
        row = next(item for item in result["rules"] if item["ruleId"] == "analytics_events")
        self.assertEqual(row["removedCount"], 1)
        with analytics_store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) n FROM events").fetchone()["n"], 1)
        audit = next(item for item in retention.audit_rows(self.db) if item["ruleId"] == "analytics_events")
        self.assertEqual(audit["mode"], "dry_run")

    def test_legal_evidence_policy_requires_explicit_legal_review(self):
        payload = {
            "ruleId": "contract_consent_receipts",
            "activeDays": 3650,
            "justification": "Conservation probatoire après validation du conseil juridique.",
            "enabled": True,
        }
        with self.assertRaises(ValueError):
            retention.save_policy(payload, self.db)
        payload["legalReviewConfirmed"] = True
        saved = retention.save_policy(payload, self.db)
        self.assertTrue(saved["ready"])
        self.assertTrue(saved["legalReviewConfirmed"])
        self.assertEqual(saved["activeDays"], 3650)

    def test_configured_notification_policy_physically_purges_old_delivery_rows(self):
        retention.save_policy({
            "ruleId": "notification_delivery",
            "activeDays": 30,
            "justification": "Diagnostic de remise limité au besoin opérationnel courant.",
            "enabled": True,
        }, self.db)
        notification_broker.init_db()
        with notification_broker.connect() as db:
            for key, age in (("old", 40), ("new", 2)):
                db.execute(
                    """INSERT INTO notification_delivery(
                         idempotency_key,channel,category,reference,recipient_hash,status,
                         attempts,created_at,last_attempt_at,sent_at,last_error
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        key, "email", "ct_due_reminder", key, "d" * 64, "sent",
                        1, self._iso(age), self._iso(age), self._iso(age), "",
                    ),
                )
        with mock.patch.object(retention.site_config_store, "load", return_value=self._site_config()):
            result = retention.run_once(dry_run=False, db_path=self.db)
        row = next(item for item in result["rules"] if item["ruleId"] == "notification_delivery")
        self.assertEqual(row["removedCount"], 1)
        with notification_broker.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) n FROM notification_delivery").fetchone()["n"], 1)

    def test_security_purge_keeps_unacknowledged_alerts(self):
        retention.save_policy({
            "ruleId": "security_telemetry",
            "activeDays": 30,
            "justification": "Fenêtre de détection Sentinel limitée aux investigations courantes.",
            "enabled": True,
        }, self.db)
        self.security_guard.init_db()
        self.security_behavior.init_db()
        self.security_alerts.init_db()
        old = self._iso(45)
        new = self._iso(2)
        old_day = old[:10]
        with __import__("sqlite3").connect(self.security_guard.DB) as db:
            db.execute(
                """INSERT INTO security_events(
                     occurred_at,client_hash,method,path,status,risk,action,reason
                   ) VALUES(?,?,?,?,?,?,?,?)""",
                (old, "client-old", "GET", "/", 200, 10, "allow", ""),
            )
            db.execute(
                """INSERT INTO behavior_profiles(
                     day,fingerprint,client_hash,first_seen,last_seen,requests,errors,
                     unique_paths,max_risk,classification
                   ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (old_day, "fp-old", "client-old", old, old, 1, 0, 1, 10, "normal"),
            )
            db.execute(
                """INSERT INTO security_alerts(
                     created_at,level,kind,title,detail,fingerprint,dedup_key,metadata_json,
                     acknowledged,delivered
                   ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (old, "medium", "old-resolved", "Resolved", "", "", "resolved", "{}", 1, 1),
            )
            db.execute(
                """INSERT INTO security_alerts(
                     created_at,level,kind,title,detail,fingerprint,dedup_key,metadata_json,
                     acknowledged,delivered
                   ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (old, "high", "old-open", "Open", "", "", "open", "{}", 0, 0),
            )
            db.execute(
                """INSERT INTO security_alerts(
                     created_at,level,kind,title,detail,fingerprint,dedup_key,metadata_json,
                     acknowledged,delivered
                   ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (new, "low", "new-resolved", "New", "", "", "new", "{}", 1, 1),
            )

        with mock.patch.object(retention.site_config_store, "load", return_value=self._site_config()):
            result = retention.run_once(dry_run=False, db_path=self.db)
        row = next(item for item in result["rules"] if item["ruleId"] == "security_telemetry")
        self.assertEqual(row["state"], "ready")
        self.assertGreaterEqual(row["removedCount"], 3)
        with __import__("sqlite3").connect(self.security_guard.DB) as db:
            events = db.execute("SELECT COUNT(*) FROM security_events").fetchone()[0]
            profiles = db.execute("SELECT COUNT(*) FROM behavior_profiles").fetchone()[0]
            open_alert = db.execute(
                "SELECT COUNT(*) FROM security_alerts WHERE kind='old-open'"
            ).fetchone()[0]
            resolved_old = db.execute(
                "SELECT COUNT(*) FROM security_alerts WHERE kind='old-resolved'"
            ).fetchone()[0]
            new_alert = db.execute(
                "SELECT COUNT(*) FROM security_alerts WHERE kind='new-resolved'"
            ).fetchone()[0]
        self.assertEqual(events, 0)
        self.assertEqual(profiles, 0)
        self.assertEqual(open_alert, 1)
        self.assertEqual(resolved_old, 0)
        self.assertEqual(new_alert, 1)

    def test_referral_ledger_stays_blocked_until_compaction_preserves_balances(self):
        retention.save_policy({
            "ruleId": "referral_ledger",
            "activeDays": 3650,
            "justification": "Conservation comptable et contestation du programme de parrainage.",
            "legalReviewConfirmed": True,
            "enabled": True,
        }, self.db)
        with mock.patch.object(retention.site_config_store, "load", return_value=self._site_config()):
            state = retention.status(self.db)
        blockers = {item["ruleId"]: item["reason"] for item in state["blockers"]}
        self.assertFalse(state["bound"])
        self.assertEqual(blockers["referral_ledger"], "purger_implementation_required")

    def test_cron_process_reports_policy_blockers_without_failing_tick(self):
        with mock.patch.object(retention.site_config_store, "load", return_value=self._site_config()):
            result = retention.process_once(self.db)
        self.assertTrue(result["ok"])
        self.assertEqual(result["state"], "partial_policy")
        self.assertFalse(result["policyComplete"])
        self.assertGreater(result["blockerCount"], 0)


if __name__ == "__main__":
    unittest.main()
