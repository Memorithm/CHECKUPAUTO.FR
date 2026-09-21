import hashlib
import os
import tempfile
import unittest
from pathlib import Path

import privacy_suppression as privacy


class PrivacySuppressionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old_private = os.environ.get("CYBERCHECK_PRIVATE_DIR")
        os.environ["CYBERCHECK_PRIVATE_DIR"] = self.tmp.name
        self.addCleanup(self._restore)
        self.db = Path(self.tmp.name) / "compliance.sqlite3"

    def _restore(self):
        if self.old_private is None:
            os.environ.pop("CYBERCHECK_PRIVATE_DIR", None)
        else:
            os.environ["CYBERCHECK_PRIVATE_DIR"] = self.old_private

    def test_hmac_identity_is_stable_and_not_plain_sha256(self):
        first = privacy.identity_hash("email", "Alice@Example.Test")
        second = privacy.identity_hash("email", "alice@example.test")
        plain = hashlib.sha256(b"alice@example.test").hexdigest()
        self.assertEqual(first, second)
        self.assertNotEqual(first, plain)
        key = Path(self.tmp.name) / "privacy-suppression-key"
        self.assertTrue(key.exists())
        self.assertEqual(key.stat().st_mode & 0o777, 0o600)

    def test_all_processing_suppresses_each_channel(self):
        privacy.suppress(
            "email",
            "alice@example.test",
            ["all_processing"],
            source_request_id="request",
            db_path=self.db,
        )
        self.assertTrue(
            privacy.is_suppressed("email", "alice@example.test", "ct_reminder", db_path=self.db)
        )
        self.assertTrue(
            privacy.is_suppressed("email", "alice@example.test", "google_review", db_path=self.db)
        )
        self.assertTrue(
            privacy.is_suppressed("email", "alice@example.test", "all_processing", db_path=self.db)
        )

    def test_marketing_suppression_does_not_stop_transactional_reminder(self):
        privacy.suppress(
            "email",
            "alice@example.test",
            privacy.DIRECT_MARKETING_PURPOSES,
            db_path=self.db,
        )
        self.assertTrue(
            privacy.is_suppressed(
                "email", "alice@example.test", "direct_marketing_email", db_path=self.db
            )
        )
        self.assertFalse(
            privacy.is_suppressed("email", "alice@example.test", "ct_reminder", db_path=self.db)
        )

    def test_unsuppress_deactivates_only_requested_purpose(self):
        privacy.suppress(
            "email",
            "alice@example.test",
            ["google_review", "ct_reminder"],
            db_path=self.db,
        )
        result = privacy.unsuppress(
            "email",
            "alice@example.test",
            ["google_review"],
            db_path=self.db,
        )
        self.assertEqual(result["deactivated"], 1)
        self.assertFalse(
            privacy.is_suppressed("email", "alice@example.test", "google_review", db_path=self.db)
        )
        self.assertTrue(
            privacy.is_suppressed("email", "alice@example.test", "ct_reminder", db_path=self.db)
        )


if __name__ == "__main__":
    unittest.main()
