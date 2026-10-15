"""Session auth regression: never write-lock on every GET; expiry and logout stay strict."""
from __future__ import annotations

import datetime as dt
import hashlib
import os
from pathlib import Path
import secrets
import tempfile
import unittest
from unittest.mock import patch

import customer_accounts as accounts


class SessionReadPathTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.data = root / "data"
        self.private = root / "private"
        self.data.mkdir()
        self.private.mkdir()
        env = patch.dict(os.environ, {"CYBERCHECK_DATA_DIR": str(self.data),
                                       "CYBERCHECK_PRIVATE_DIR": str(self.private)})
        env.start()
        self.addCleanup(env.stop)
        accounts.init_db()
        self.account = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        self.token = secrets.token_urlsafe(48)
        self.digest = hashlib.sha256(self.token.encode()).hexdigest()
        self.now = dt.datetime(2026, 10, 15, 15, 0, tzinfo=dt.timezone.utc)
        self.addCleanup(patch.stopall)
        with accounts._connect() as db:
            db.execute(
                "INSERT INTO customer_account(account_id,kind,email_hash,profile_blob,created_at,updated_at)"
                " VALUES(?,?,?,?,?,?)",
                (self.account, "individual", "a" * 64, b"unused-profile",
                 self.now.isoformat(), self.now.isoformat()),
            )
            db.execute(
                "INSERT INTO customer_session(session_hash,account_id,created_at,expires_at,last_seen_at)"
                " VALUES(?,?,?,?,?)",
                (self.digest, self.account, self.now.isoformat(),
                 (self.now + dt.timedelta(hours=2)).isoformat(),
                 self.now.isoformat()),
            )
        accounts._ensure_schema()

    def _trace_verify(self):
        sql = []
        real = accounts._connect
        def traced():
            db = real()
            db.set_trace_callback(sql.append)
            return db
        with patch.object(accounts, "_now", return_value=self.now), patch.object(
            accounts, "_connect", side_effect=traced
        ):
            account_id = accounts.authenticate_session(self.token)
        return account_id, sql

    def test_active_session_read_does_not_begin_immediate_or_update(self):
        account, queries = self._trace_verify()
        self.assertEqual(account, self.account)
        normalized = " ".join(queries).upper()
        self.assertNotIn("BEGIN IMMEDIATE", normalized)
        self.assertNotIn("UPDATE CUSTOMER_SESSION", normalized)

    def test_last_seen_is_refreshed_when_stale_only_once(self):
        with accounts._connect() as db:
            db.execute(
                "UPDATE customer_session SET last_seen_at=? WHERE session_hash=?",
                ((self.now - dt.timedelta(minutes=20)).isoformat(), self.digest)
            )
        account, sql = self._trace_verify()
        self.assertEqual(account, self.account)
        self.assertIn("UPDATE CUSTOMER_SESSION", " ".join(sql).upper())
        _, second = self._trace_verify()
        self.assertNotIn("UPDATE CUSTOMER_SESSION", " ".join(second).upper())

    def test_logout_removes_session_and_cannot_be_reauthenticated(self):
        self.assertEqual(self._trace_verify()[0], self.account)
        accounts.close_session(self.token)
        with self.assertRaisesRegex(PermissionError, "customer_session_invalid"):
            self._trace_verify()

    def test_expired_session_is_denied_without_refresh(self):
        with accounts._connect() as db:
            db.execute(
                "UPDATE customer_session SET expires_at=? WHERE session_hash=?",
                ((self.now - dt.timedelta(seconds=1)).isoformat(), self.digest)
            )
        with self.assertRaisesRegex(PermissionError, "customer_session_expired"):
            self._trace_verify()

    def test_unknown_token_rejected_without_privileged_write(self):
        with self.assertRaisesRegex(PermissionError, "customer_session_invalid"):
            with patch.object(accounts, "_now", return_value=self.now):
                accounts.authenticate_session(secrets.token_urlsafe(48))


if __name__ == "__main__":
    unittest.main()
