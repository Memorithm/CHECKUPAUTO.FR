import datetime as dt
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

import analytics_store
import compliance_store
import customer_account_rights
import customer_accounts
import customer_booking_journal as journal
import customer_oidc
import customer_password_auth as passwords
import mobile_auth_ticket
import retention_enforcement as retention


def _iso(delta_days=0, **kw):
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=delta_days, **kw)).isoformat(timespec="seconds")


class RetentionCustomerDataTest(unittest.TestCase):
    """R-01: customer data classes get enforced retention; erasure covers the booking journal."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "data").mkdir(); (self.root / "private").mkdir()
        env = mock.patch.dict(os.environ, {"CYBERCHECK_DATA_DIR": str(self.root / "data"), "CYBERCHECK_PRIVATE_DIR": str(self.root / "private")}, clear=False)
        env.start(); self.addCleanup(env.stop)
        previous = analytics_store.DB
        analytics_store.DB = self.root / "analytics.sqlite3"
        self.addCleanup(setattr, analytics_store, "DB", previous)
        self.compliance = self.root / "compliance.sqlite3"

    def account(self, email="alice@example.test", subject="alice-sub"):
        return customer_accounts.create_from_verified_identity("google", subject, email, "Alice", email_verified=True)

    def test_new_rules_are_registered_with_safe_modes(self):
        for rule in ("customer_expired_sessions", "customer_password_transient", "customer_oidc_flows", "mobile_auth_tickets", "customer_booking_abandoned"):
            self.assertIn(rule, retention.AUTO_RULES)
            self.assertTrue(retention.policy(rule, self.compliance)["ready"])
        for rule in ("customer_inactive_accounts", "customer_booking_confirmed"):
            self.assertIn(rule, retention.CONFIGURABLE_RULES)
            self.assertFalse(retention.policy(rule, self.compliance)["ready"])
        self.assertTrue(retention.CONFIGURABLE_RULES["customer_booking_confirmed"]["legalReviewRequired"])

    def test_expired_sessions_are_purged_and_live_ones_kept(self):
        alice = self.account()
        live = customer_accounts.issue_session(alice["accountId"])
        expired = customer_accounts.issue_session(alice["accountId"])
        import hashlib
        with customer_accounts._connect() as db:
            db.execute(
                "UPDATE customer_session SET expires_at=? WHERE session_hash=?",
                (_iso(-1), hashlib.sha256(expired["token"].encode()).hexdigest()),
            )
        self.assertEqual(customer_accounts.purge_expired_sessions(dry_run=True), 1)
        self.assertEqual(customer_accounts.purge_expired_sessions(), 1)
        with customer_accounts._connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM customer_session").fetchone()[0], 1)
        self.assertEqual(customer_accounts.authenticate_session(live["token"]), alice["accountId"])

    def test_pending_signups_tokens_and_stale_throttles_are_purged(self):
        pending = passwords.begin_registration("bob@example.test", None, "Long enough passphrase 1")
        with customer_accounts._connect() as db:
            db.execute("UPDATE customer_password_credential SET created_at=?", (_iso(-2),))
            db.execute("UPDATE customer_password_token SET expires_at=?", (_iso(-1),))
        removed = passwords.purge_stale()
        self.assertGreaterEqual(removed, 2)
        with customer_accounts._connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM customer_account").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM customer_password_token").fetchone()[0], 0)
        with self.assertRaises(PermissionError):
            passwords.verify_registration(pending["token"])

    def test_federated_account_with_unverified_credential_is_not_deleted(self):
        alice = self.account()
        with customer_accounts._connect() as db:
            db.execute(
                "INSERT INTO customer_password_credential(account_id,password_hash,verified_at,failed_attempts,locked_until,created_at,updated_at,last_login_at) VALUES(?,?,'',0,'',?,?,'')",
                (alice["accountId"], "x", _iso(-5), _iso(-5)),
            )
        passwords.purge_stale()
        self.assertEqual(customer_accounts.profile(alice["accountId"])["accountId"], alice["accountId"])

    def test_expired_oidc_flows_are_purged(self):
        customer_oidc.init_db()
        with customer_oidc._connect() as db:
            for name, expiry in (("old", _iso(-1)), ("new", _iso(1))):
                db.execute(
                    "INSERT INTO customer_oidc_flow(state_hash,provider,nonce,verifier,redirect_uri,created_at,expires_at) VALUES(?,?,?,?,?,?,?)",
                    (name, "google", "n", "v", "https://www.checkupauto.fr/cb", _iso(-2), expiry),
                )
        self.assertEqual(customer_oidc.purge_expired_flows(), 1)
        with customer_oidc._connect() as db:
            self.assertEqual([r[0] for r in db.execute("SELECT state_hash FROM customer_oidc_flow")], ["new"])

    def test_expired_mobile_tickets_are_purged_without_new_issue(self):
        ticket = mobile_auth_ticket.issue("session-token")
        with sqlite3.connect(mobile_auth_ticket._path()) as db:
            db.execute("UPDATE mobile_auth_ticket SET expires_at=?", (_iso(-1),))
        self.assertEqual(mobile_auth_ticket.purge_expired(), 1)
        with self.assertRaises(PermissionError):
            mobile_auth_ticket.consume(ticket)

    def test_booking_journal_purges_only_abandoned_prepared_rows(self):
        alice = self.account()["accountId"]
        journal.prepare(account_id=alice, key="k" * 24, request={"a": 1})
        journal.prepare(account_id=alice, key="r" * 24, request={"a": 2})
        journal.require_reconciliation(account_id=alice, key="r" * 24)
        with sqlite3.connect(journal.database_path()) as db:
            db.execute("UPDATE booking_request SET updated_at=?", (_iso(-40),))
        self.assertEqual(journal.purge_abandoned(_iso(-30)), 1)
        # Ambiguous provider writes are never purged automatically.
        self.assertEqual(journal.status(account_id=alice, key="r" * 24)["state"], "reconciliation_required")

    def test_account_erasure_removes_booking_journal_rows(self):
        alice = self.account()["accountId"]
        bob = self.account("bob@example.test", "bob-sub")["accountId"]
        journal.prepare(account_id=alice, key="a" * 24, request={"x": 1})
        journal.prepare(account_id=bob, key="b" * 24, request={"x": 1})
        req = compliance_store.create_rights_request({"type": "erasure", "subjectRef": "alice@example.test", "notes": ""}, self.compliance)
        out = customer_account_rights.execute(req["id"], "alice@example.test", self.compliance)
        self.assertEqual(out["remainingAccountCount"], 0)
        self.assertEqual(journal.remaining_for_account(alice), 0)
        self.assertEqual(journal.remaining_for_account(bob), 1)

    def test_inactive_account_purge_keeps_active_and_wallet_holders(self):
        stale = self.account("stale@example.test", "stale-sub")["accountId"]
        holder = self.account("holder@example.test", "holder-sub")["accountId"]
        active = self.account("active@example.test", "active-sub")["accountId"]
        old = _iso(-1200)
        with customer_accounts._connect() as db:
            db.execute("UPDATE customer_account SET created_at=?,updated_at=? WHERE account_id IN (?,?)", (old, old, stale, holder))
            db.execute("UPDATE customer_identity SET last_login_at=? WHERE account_id IN (?,?)", (old, stale, holder))
        journal.prepare(account_id=stale, key="s" * 24, request={"x": 1})
        real_profile = customer_accounts.profile

        def profile(account_id):
            data = real_profile(account_id)
            if account_id == holder:
                data["loyalty"]["balanceCents"] = 500
            return data

        with mock.patch.object(customer_accounts, "profile", side_effect=profile):
            self.assertEqual(retention._purge_inactive_customer_accounts(1095, dry_run=True), 1)
            self.assertEqual(retention._purge_inactive_customer_accounts(1095, dry_run=False), 1)
        with self.assertRaises(customer_accounts.CustomerAccountError):
            customer_accounts.profile(stale)
        self.assertEqual(journal.remaining_for_account(stale), 0)
        self.assertEqual(customer_accounts.profile(holder)["accountId"], holder)
        self.assertEqual(customer_accounts.profile(active)["accountId"], active)

    def test_inactive_policy_enforces_minimum_one_year(self):
        with self.assertRaises(ValueError):
            retention.save_policy({"ruleId": "customer_inactive_accounts", "activeDays": 30, "justification": "trop court pour test"}, self.compliance)
        saved = retention.save_policy({"ruleId": "customer_inactive_accounts", "activeDays": 1095, "justification": "3 ans après le dernier contact (CNIL)"}, self.compliance)
        self.assertTrue(saved["ready"])


if __name__ == "__main__":
    unittest.main()
