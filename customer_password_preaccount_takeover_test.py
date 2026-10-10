import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import analytics_store as analytics
import customer_accounts as accounts
import customer_http as http
import customer_password_auth as passwords
from customer_http_test import Handler


VICTIM = "victim@example.test"
ATTACKER_PASSWORD = "Attacker chosen passphrase 1"
VICTIM_PASSWORD = "Victim chosen passphrase 22"


class PreAccountTakeoverTest(unittest.TestCase):
    """S-02: sign-up must never seed a password on an account owned by someone else."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "data").mkdir(); (root / "private").mkdir()
        env = patch.dict(os.environ, {"CYBERCHECK_DATA_DIR": str(root / "data"), "CYBERCHECK_PRIVATE_DIR": str(root / "private")}, clear=False)
        env.start(); self.addCleanup(env.stop)
        previous = analytics.DB
        analytics.DB = root / "analytics.sqlite3"
        self.addCleanup(setattr, analytics, "DB", previous)

    def test_signup_on_federated_account_does_not_attach_attacker_password(self):
        federated = accounts.create_from_verified_identity("google", "sub-victim", VICTIM, "Victim", email_verified=True)
        attempt = passwords.begin_registration(VICTIM, None, ATTACKER_PASSWORD)
        # The mailbox owner gets a link to choose a password; nothing is stored yet.
        self.assertEqual(attempt["purpose"], "reset")
        self.assertFalse(passwords.status(federated["accountId"])["configured"])
        with self.assertRaises(PermissionError):
            passwords.authenticate(VICTIM, ATTACKER_PASSWORD)
        # A verification link cannot activate anything for this account.
        with self.assertRaises(PermissionError):
            passwords.verify_registration(attempt["token"])
        # Only the person holding the e-mailed link chooses the password.
        profile = passwords.reset_password(attempt["token"], VICTIM_PASSWORD)
        self.assertEqual(profile["accountId"], federated["accountId"])
        self.assertEqual(profile["providers"], ["google"])
        self.assertEqual(passwords.authenticate(VICTIM, VICTIM_PASSWORD)["accountId"], federated["accountId"])
        with self.assertRaises(PermissionError):
            passwords.authenticate(VICTIM, ATTACKER_PASSWORD)

    def test_resignup_does_not_overwrite_pending_password(self):
        victim = passwords.begin_registration(VICTIM, None, VICTIM_PASSWORD)
        attacker = passwords.begin_registration(VICTIM, None, ATTACKER_PASSWORD)
        self.assertEqual(victim["purpose"], "verify")
        self.assertEqual(attacker["purpose"], "reset")
        # The attacker's sign-up neither replaced the stored password nor issued
        # a verification link that would activate the attacker's password.
        with self.assertRaises(PermissionError):
            passwords.verify_registration(attacker["token"])
        with self.assertRaises(PermissionError):
            passwords.authenticate(VICTIM, ATTACKER_PASSWORD)
        # The earlier verification link is revoked; the mailbox owner uses the new
        # one-time link to choose their own password.
        with self.assertRaises(PermissionError):
            passwords.verify_registration(victim["token"])
        passwords.reset_password(attacker["token"], VICTIM_PASSWORD)
        self.assertTrue(passwords.authenticate(VICTIM, VICTIM_PASSWORD)["emailVerified"])
        with self.assertRaises(PermissionError):
            passwords.authenticate(VICTIM, ATTACKER_PASSWORD)

    def test_attacker_first_signup_then_victim_signup_never_activates_attacker_password(self):
        attacker = passwords.begin_registration(VICTIM, None, ATTACKER_PASSWORD)
        victim = passwords.begin_registration(VICTIM, None, VICTIM_PASSWORD)
        with self.assertRaises(PermissionError):
            passwords.verify_registration(attacker["token"])
        passwords.reset_password(victim["token"], VICTIM_PASSWORD)
        with self.assertRaises(PermissionError):
            passwords.authenticate(VICTIM, ATTACKER_PASSWORD)

    def test_reset_token_for_deleted_account_is_rejected(self):
        federated = accounts.create_from_verified_identity("google", "sub-gone", VICTIM, "Victim", email_verified=True)
        attempt = passwords.begin_registration(VICTIM, None, ATTACKER_PASSWORD)
        with accounts._connect() as db:
            db.execute("DELETE FROM customer_account WHERE account_id=?", (federated["accountId"],))
        with self.assertRaises(PermissionError):
            passwords.reset_password(attempt["token"], VICTIM_PASSWORD)

    def test_verification_link_confirms_without_opening_a_session(self):
        pending = passwords.begin_registration(VICTIM, None, VICTIM_PASSWORD)
        h = Handler("/compte/verifier-email?token=" + pending["token"])
        self.assertTrue(http.handle(h))
        self.assertEqual(h.response["status"], 200)
        self.assertIn("Adresse e-mail confirmée", h.response["data"].decode())
        self.assertNotIn("Set-Cookie", h.response["headers"])
        with accounts._connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM customer_session").fetchone()[0], 0)
        # The person must still know the password to get in.
        self.assertTrue(passwords.authenticate(VICTIM, VICTIM_PASSWORD)["emailVerified"])


if __name__ == "__main__":
    unittest.main()
