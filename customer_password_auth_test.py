import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import analytics_store as analytics
import customer_accounts as accounts
import customer_password_auth as passwords


class CustomerPasswordAuthTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        data=root/"data"; private=root/"private"
        data.mkdir(); private.mkdir()
        self.env=patch.dict(os.environ,{
            "CYBERCHECK_DATA_DIR":str(data),
            "CYBERCHECK_PRIVATE_DIR":str(private),
        },clear=False)
        self.env.start(); self.addCleanup(self.env.stop)
        self.previous_db=analytics.DB
        analytics.DB=root/"analytics.sqlite3"
        self.addCleanup(setattr,analytics,"DB",self.previous_db)

    def register(self,email="client@example.test",password="Correct horse battery 42"):
        return passwords.begin_registration(email,"Client Test",password)

    def test_registration_requires_one_time_email_verification_then_allows_login(self):
        pending=self.register()
        self.assertEqual(pending["purpose"],"verify")
        with self.assertRaisesRegex(accounts.CustomerAccountError,"customer_email_not_verified"):
            passwords.authenticate("client@example.test","Correct horse battery 42")

        profile=passwords.verify_registration(pending["token"])
        self.assertTrue(profile["passwordConfigured"])
        self.assertTrue(profile["emailVerified"])
        self.assertEqual(profile["providers"],[])
        logged=passwords.authenticate("CLIENT@example.test","Correct horse battery 42")
        self.assertEqual(logged["accountId"],profile["accountId"])
        with self.assertRaises(PermissionError):
            passwords.verify_registration(pending["token"])

        raw=accounts.data_path().read_bytes()
        self.assertNotIn(b"Correct horse battery 42",raw)
        self.assertNotIn(pending["token"].encode(),raw)
        self.assertNotIn(b"client@example.test",raw)

    def test_existing_federated_account_can_add_verified_email_password_without_duplicate(self):
        federated=accounts.create_from_verified_identity(
            "google","subject-1","client@example.test","Client Test",email_verified=True,
        )
        pending=self.register()
        verified=passwords.verify_registration(pending["token"])
        self.assertEqual(verified["accountId"],federated["accountId"])
        self.assertTrue(verified["passwordConfigured"])
        self.assertEqual(verified["providers"],["google"])
        self.assertEqual(passwords.authenticate("client@example.test","Correct horse battery 42")["accountId"],federated["accountId"])

    def test_registration_on_existing_local_account_issues_reset_not_duplicate(self):
        first=self.register()
        profile=passwords.verify_registration(first["token"])
        second=passwords.begin_registration("client@example.test","Other Name","New password phrase 99")
        self.assertEqual(second["purpose"],"reset")
        changed=passwords.reset_password(second["token"],"New password phrase 99")
        self.assertEqual(changed["accountId"],profile["accountId"])
        with self.assertRaises(PermissionError):
            passwords.authenticate("client@example.test","Correct horse battery 42")
        self.assertEqual(passwords.authenticate("client@example.test","New password phrase 99")["accountId"],profile["accountId"])

    def test_password_reset_revokes_existing_sessions(self):
        pending=self.register()
        profile=passwords.verify_registration(pending["token"])
        session=accounts.issue_session(profile["accountId"])
        reset=passwords.begin_reset("client@example.test")
        self.assertTrue(reset["deliver"])
        passwords.reset_password(reset["token"],"Replacement password phrase 77")
        with self.assertRaises(PermissionError):
            accounts.authenticate_session(session["token"])
        with self.assertRaises(PermissionError):
            passwords.reset_password(reset["token"],"Another replacement phrase 88")
        self.assertEqual(passwords.authenticate("client@example.test","Replacement password phrase 77")["accountId"],profile["accountId"])

    def test_wrong_password_is_generic_and_eventually_locks_account(self):
        pending=self.register()
        passwords.verify_registration(pending["token"])
        for _ in range(passwords.LOGIN_FAILURE_LIMIT):
            with self.assertRaisesRegex(PermissionError,"customer_login_invalid"):
                passwords.authenticate("client@example.test","incorrect but long password")
        with self.assertRaisesRegex(PermissionError,"customer_login_invalid"):
            passwords.authenticate("client@example.test","Correct horse battery 42")
        with accounts._connect() as db:
            row=db.execute("SELECT failed_attempts,locked_until FROM customer_password_credential").fetchone()
        self.assertGreaterEqual(int(row["failed_attempts"]),passwords.LOGIN_FAILURE_LIMIT)
        self.assertTrue(row["locked_until"])

    def test_invalid_or_unknown_reset_request_is_enumeration_safe(self):
        self.assertEqual(passwords.begin_reset("nobody@example.test"),{"ok":True,"deliver":False})
        self.assertEqual(passwords.begin_reset("not-an-email"),{"ok":True,"deliver":False})

    def test_password_policy_rejects_short_password_and_email_as_password(self):
        with self.assertRaisesRegex(accounts.CustomerAccountError,"customer_password_policy_invalid"):
            passwords.begin_registration("client@example.test","Client Test","short")
        with self.assertRaisesRegex(accounts.CustomerAccountError,"customer_password_policy_invalid"):
            passwords.begin_registration("client@example.test","Client Test","client@example.test")


if __name__=="__main__":
    unittest.main()
