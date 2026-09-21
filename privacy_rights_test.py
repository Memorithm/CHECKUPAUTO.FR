import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import privacy_rights as rights
import privacy_suppression as suppression


class PrivacyRightsTest(unittest.TestCase):
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

    def create(self, request_type="objection", **extra):
        payload = {
            "type": request_type,
            "subjectKind": "email",
            "subjectRef": "alice@example.test",
            "purpose": "direct_marketing",
            "notes": "verified request",
        }
        payload.update(extra)
        return rights.create_request(payload, self.db)

    def test_objection_closes_after_enforced_marketing_suppression(self):
        request = self.create()
        result = rights.execute_request(request["id"], self.db)
        self.assertEqual(result["state"], "closed")
        self.assertTrue(
            suppression.is_suppressed(
                "email",
                "alice@example.test",
                "direct_marketing_email",
                db_path=self.db,
            )
        )
        self.assertFalse(
            suppression.is_suppressed(
                "email",
                "alice@example.test",
                "ct_reminder",
                db_path=self.db,
            )
        )
        detail = rights.request_details(request["id"], self.db)
        self.assertFalse(detail["locatorAvailable"])

    def test_consent_withdrawal_cannot_silence_unrelated_processing(self):
        with self.assertRaises(ValueError):
            self.create("consent_withdrawal", purpose="all_processing")

    def test_erasure_requires_provider_evidence_before_closure(self):
        request = self.create("erasure")
        with mock.patch.object(rights, "_reminder_rows", return_value=[]), \
             mock.patch.object(rights, "_mobile_rows", return_value=[]), \
             mock.patch.object(rights, "_reminder_delete", return_value=2), \
             mock.patch.object(rights, "_mobile_delete", return_value=1), \
             mock.patch.object(rights, "_notification_delete", return_value=3), \
             mock.patch.object(rights, "_review_delete", return_value=0), \
             mock.patch.object(rights, "_booking_rows", return_value=[]), \
             mock.patch.object(
                 rights,
                 "_compliance_contract_rows",
                 return_value={"consentReceipts": [], "withdrawalRequests": []},
             ):
            result = rights.execute_request(request["id"], self.db)

        self.assertEqual(result["state"], "in_progress")
        mercure = next(
            step for step in result["steps"]
            if step["store"] == "mercure" and step["action"] == "erasure"
        )
        self.assertEqual(mercure["status"], "manual_required")
        with self.assertRaises(RuntimeError):
            rights.complete_request(request["id"], self.db)

        rights.complete_manual_step(
            request["id"],
            "mercure",
            "erasure",
            evidence_code="provider-ticket-123",
            db_path=self.db,
        )
        closed = rights.complete_request(request["id"], self.db)
        self.assertEqual(closed["status"], "closed")
        self.assertTrue(closed["locatorCleared"])

    def test_access_export_is_generated_without_persisting_payload(self):
        request = self.create("access")
        with mock.patch.object(rights, "_reminder_rows", return_value=[{"vehicleId": "v1"}]), \
             mock.patch.object(rights, "_mobile_rows", return_value=[]), \
             mock.patch.object(rights, "_notification_rows", return_value=[{"status": "sent"}]), \
             mock.patch.object(rights, "_review_rows", return_value=[]), \
             mock.patch.object(rights, "_booking_rows", return_value=[]), \
             mock.patch.object(
                 rights,
                 "_compliance_contract_rows",
                 return_value={"consentReceipts": [], "withdrawalRequests": []},
             ), \
             mock.patch.object(rights, "_mercure_snapshot", return_value=None):
            result = rights.execute_request(request["id"], self.db)

        self.assertEqual(result["state"], "export_generated")
        self.assertEqual(
            result["export"]["stores"]["reminders"],
            [{"vehicleId": "v1"}],
        )
        self.assertEqual(
            result["export"]["stores"]["notifications"],
            [{"status": "sent"}],
        )
        raw = Path(self.tmp.name, "compliance.sqlite3").read_bytes()
        self.assertNotIn(b"alice@example.test", raw)


if __name__ == "__main__":
    unittest.main()
