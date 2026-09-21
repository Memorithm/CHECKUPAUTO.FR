import hashlib
import os
import tempfile
import unittest
from pathlib import Path

import compliance_store
import data_subject_rights as rights
import privacy_suppression as privacy


class PrivacySuppressionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old_private = os.environ.get("CYBERCHECK_PRIVATE_DIR")
        self.old_data = os.environ.get("CYBERCHECK_DATA_DIR")
        os.environ["CYBERCHECK_PRIVATE_DIR"] = self.tmp.name
        os.environ["CYBERCHECK_DATA_DIR"] = self.tmp.name
        self.addCleanup(self._restore)
        self.db = Path(self.tmp.name) / "compliance.sqlite3"

    def _restore(self):
        for key, value in (
            ("CYBERCHECK_PRIVATE_DIR", self.old_private),
            ("CYBERCHECK_DATA_DIR", self.old_data),
        ):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def request(self, request_type, subject="alice@example.test"):
        return compliance_store.create_rights_request(
            {"type": request_type, "subjectRef": subject},
            self.db,
        )

    def test_registry_uses_private_key_hmac(self):
        digest = privacy.identity_hash("email", "Alice@Example.Test")
        plain = hashlib.sha256(b"alice@example.test").hexdigest()
        self.assertNotEqual(digest, plain)
        key = Path(self.tmp.name) / "privacy-suppression-key"
        self.assertTrue(key.exists())
        self.assertEqual(key.stat().st_mode & 0o777, 0o600)

    def test_objection_defaults_to_direct_marketing_only(self):
        request = self.request("objection")
        result = rights.execute(
            request["id"],
            "alice@example.test",
            adapter="privacy_suppression",
            purpose="direct_marketing",
            db_path=self.db,
        )
        self.assertEqual(result["adapter"], "privacy_suppression")
        self.assertTrue(
            privacy.is_suppressed(
                "email", "alice@example.test", "direct_marketing_email", db_path=self.db
            )
        )
        self.assertFalse(
            privacy.is_suppressed(
                "email", "alice@example.test", "ct_reminder", db_path=self.db
            )
        )
        self.assertEqual(
            compliance_store.rights_requests(self.db)[0]["status"],
            "in_progress",
        )

    def test_restriction_blocks_all_processing_purposes(self):
        request = self.request("restriction")
        rights.execute(
            request["id"],
            "alice@example.test",
            adapter="privacy_suppression",
            db_path=self.db,
        )
        self.assertTrue(
            privacy.is_suppressed("email", "alice@example.test", "ct_reminder", db_path=self.db)
        )
        self.assertTrue(
            privacy.is_suppressed("email", "alice@example.test", "google_review", db_path=self.db)
        )

    def test_consent_withdrawal_cannot_target_review_without_documented_consent(self):
        request = self.request("consent_withdrawal")
        with self.assertRaises(ValueError):
            rights.execute(
                request["id"],
                "alice@example.test",
                adapter="privacy_suppression",
                purpose="google_review",
                db_path=self.db,
            )


if __name__ == "__main__":
    unittest.main()
