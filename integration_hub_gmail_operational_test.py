import sqlite3
import tempfile
import unittest
from pathlib import Path

import gmail_operational_evidence as evidence
import integration_hub as hub


class IntegrationHubGmailOperationalTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.original = (
            hub.PRIVATE_DIR, hub.INTEGRATION_DIR, hub.CLIENT_FILE,
            hub.TOKEN_FILE, hub.SETTINGS_FILE, hub.STATE_FILE, evidence.DB,
        )
        hub.PRIVATE_DIR = root
        hub.INTEGRATION_DIR = root / "integrations"
        hub.CLIENT_FILE = hub.INTEGRATION_DIR / "google-oauth-client.json"
        hub.TOKEN_FILE = hub.INTEGRATION_DIR / "google-oauth-token.json"
        hub.SETTINGS_FILE = hub.INTEGRATION_DIR / "google-settings.json"
        hub.STATE_FILE = hub.INTEGRATION_DIR / "google-oauth-state.json"
        evidence.DB = root / "notification-broker.sqlite3"
        hub.save_oauth_client({"web": {
            "client_id": "client-id.apps.googleusercontent.com",
            "client_secret": "test-only-secret",
            "token_uri": hub.TOKEN_URL,
            "redirect_uris": ["https://www.checkupauto.fr/api/integrations/google/oauth/callback"],
        }})
        hub._atomic_json(hub.TOKEN_FILE, {
            "refresh_token": "test-only-refresh",
            "scope": "https://www.googleapis.com/auth/gmail.send",
        })
        hub.save_settings({"gmailSender": "contact@checkupauto.fr"})

    def tearDown(self):
        (hub.PRIVATE_DIR, hub.INTEGRATION_DIR, hub.CLIENT_FILE, hub.TOKEN_FILE,
         hub.SETTINGS_FILE, hub.STATE_FILE, evidence.DB) = self.original
        self.tmp.cleanup()

    def _gmail(self):
        state = hub.status({}, "https://www.checkupauto.fr", verify_remote=True)
        return next(item for item in state["connectors"] if item["id"] == "gmail")

    def _health(self, *, success="", failure="", failures=0, open_until=""):
        with sqlite3.connect(evidence.DB) as db:
            db.execute("""CREATE TABLE notification_transport_health(
                transport_key TEXT PRIMARY KEY, consecutive_failures INTEGER NOT NULL,
                open_until TEXT NOT NULL, last_failure_at TEXT NOT NULL,
                last_success_at TEXT NOT NULL)""")
            db.execute(
                "INSERT INTO notification_transport_health VALUES(?,?,?,?,?)",
                (evidence.TRANSPORT_KEY, failures, open_until, failure, success),
            )

    def test_authorized_gmail_without_delivery_history_is_unverified(self):
        gmail = self._gmail()
        self.assertFalse(gmail["connected"])
        self.assertEqual(gmail["state"], "attention")
        self.assertEqual(gmail["verification"], "unverified")
        self.assertEqual(gmail["verificationSource"], "operational_delivery")
        self.assertNotIn("lastSuccessAt", gmail["operationalEvidence"])

    def test_real_delivery_marks_gmail_verified(self):
        self._health(success="2026-09-21T15:00:00+00:00")
        gmail = self._gmail()
        self.assertTrue(gmail["connected"])
        self.assertEqual(gmail["verification"], "verified")
        self.assertEqual(gmail["verificationSource"], "operational_delivery")
        self.assertTrue(gmail["operationalEvidence"]["operationallyVerified"])

    def test_recent_delivery_failure_marks_gmail_unavailable(self):
        self._health(
            success="2026-09-21T15:00:00+00:00",
            failure="2026-09-21T16:00:00+00:00", failures=1,
        )
        gmail = self._gmail()
        self.assertFalse(gmail["connected"])
        self.assertEqual(gmail["verification"], "unavailable")
        self.assertEqual(gmail["verificationSource"], "operational_delivery")
        self.assertEqual(gmail["operationalEvidence"]["consecutiveFailures"], 1)


if __name__ == "__main__":
    unittest.main()
