import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import compliance_store
import data_subject_rights


class MercureRightsCompletionAuditTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "compliance.sqlite3"

    def tearDown(self):
        self.tmp.cleanup()

    @patch.object(data_subject_rights.mercure_rights, "contact_snapshot")
    def test_complete_provider_export_records_completion_action_but_keeps_request_open(self, snapshot):
        subject_ref = "account:12"
        snapshot.return_value = {
            "provider": "mercure",
            "subject": {"clientKind": "account", "clientId": "12"},
            "contact": {"email": "client@example.fr", "telephone": "+33102030405"},
            "coverage": {
                "contact": True,
                "vehicles": True,
                "appointments": True,
                "billing": True,
            },
            "partial": False,
        }
        request = compliance_store.create_rights_request(
            {"type": "access", "subjectRef": subject_ref},
            self.db_path,
        )

        result = data_subject_rights.execute(
            request["id"],
            subject_ref,
            adapter="mercure_customer_contact",
            db_path=self.db_path,
        )

        self.assertTrue(result["ok"])
        self.assertFalse(result["data"]["partial"])
        self.assertFalse(result["requestComplete"])
        self.assertEqual(result["requestStatus"], "in_progress")
        audit = data_subject_rights.audit_rows(self.db_path)
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["adapter"], "mercure_customer_contact")
        self.assertEqual(audit[0]["action"], "export_complete")
        exposed = repr(audit)
        self.assertNotIn(subject_ref, exposed)
        self.assertNotIn("client@example.fr", exposed)
        self.assertNotIn("+33102030405", exposed)


if __name__ == "__main__":
    unittest.main()
