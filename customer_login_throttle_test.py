import datetime as dt
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import analytics_store as analytics
import customer_accounts as accounts
import customer_password_auth as passwords
from customer_password_http_test import form_handler
import customer_http as http

EMAIL = "client@example.test"
PASSWORD = "Correct horse battery 42"
ATTACKER = "a" * 20
VICTIM = "b" * 20


class CustomerLoginThrottleTest(unittest.TestCase):
    """S-03: failed logins from one client must not lock the account for everyone."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "data").mkdir(); (root / "private").mkdir()
        env = patch.dict(os.environ, {"CYBERCHECK_DATA_DIR": str(root / "data"), "CYBERCHECK_PRIVATE_DIR": str(root / "private")}, clear=False)
        env.start(); self.addCleanup(env.stop)
        previous = analytics.DB
        analytics.DB = root / "analytics.sqlite3"
        self.addCleanup(setattr, analytics, "DB", previous)
        pending = passwords.begin_registration(EMAIL, None, PASSWORD)
        passwords.verify_registration(pending["token"])

    def fail(self, client, times):
        for _ in range(times):
            with self.assertRaises(PermissionError):
                passwords.authenticate(EMAIL, "wrong but long password", client_key=client)

    def test_attacker_lock_does_not_affect_other_clients(self):
        self.fail(ATTACKER, passwords.LOGIN_FAILURE_LIMIT)
        with self.assertRaises(PermissionError):
            passwords.authenticate(EMAIL, PASSWORD, client_key=ATTACKER)
        self.assertEqual(passwords.authenticate(EMAIL, PASSWORD, client_key=VICTIM)["email"], EMAIL)

    def test_lock_is_not_extended_by_attempts_during_lock(self):
        self.fail(ATTACKER, passwords.LOGIN_FAILURE_LIMIT)
        with accounts._connect() as db:
            first = db.execute("SELECT locked_until FROM customer_password_throttle WHERE client_key=?", (ATTACKER,)).fetchone()[0]
        start = accounts._now()
        with patch.object(accounts, "_now", return_value=start + dt.timedelta(minutes=10)):
            self.fail(ATTACKER, 3)
        with accounts._connect() as db:
            again = db.execute("SELECT locked_until FROM customer_password_throttle WHERE client_key=?", (ATTACKER,)).fetchone()[0]
        self.assertEqual(first, again)
        with patch.object(accounts, "_now", return_value=start + dt.timedelta(minutes=passwords.LOGIN_LOCK_MINUTES + 1)):
            self.assertEqual(passwords.authenticate(EMAIL, PASSWORD, client_key=ATTACKER)["email"], EMAIL)

    def test_distributed_guessing_hits_account_wide_ceiling(self):
        for index in range(passwords.ACCOUNT_FAILURE_LIMIT):
            client = f"{index:020x}"
            with self.assertRaises(PermissionError):
                passwords.authenticate(EMAIL, "wrong but long password", client_key=client)
        with self.assertRaises(PermissionError):
            passwords.authenticate(EMAIL, PASSWORD, client_key=VICTIM)

    def test_password_reset_clears_throttles(self):
        self.fail(ATTACKER, passwords.LOGIN_FAILURE_LIMIT)
        reset = passwords.begin_reset(EMAIL)
        passwords.reset_password(reset["token"], "Brand new passphrase 77")
        with accounts._connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM customer_password_throttle").fetchone()[0], 0)

    def test_http_login_passes_sentinel_client_to_throttle(self):
        h = form_handler("/compte/connexion", {"email": EMAIL, "password": PASSWORD, "returnTo": ""})
        h._security_client = ATTACKER
        session = {"token": "s" * 48, "maxAge": 43200, "accountId": "x"}
        with patch.object(http.customer_password_auth, "authenticate", return_value={"accountId": "x"}) as auth, \
             patch.object(http.customer_accounts, "issue_session", return_value=session):
            self.assertTrue(http.handle(h))
        self.assertEqual(auth.call_args.kwargs["client_key"], ATTACKER)


if __name__ == "__main__":
    unittest.main()
