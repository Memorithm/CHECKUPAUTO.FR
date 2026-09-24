import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import compliance_store
import data_subject_rights as rights
import privacy_suppression


class PrivacySuppressionRetryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.compliance_db = self.root / "compliance.sqlite3"
        self.env_patch = patch.dict(
            os.environ,
            {"CYBERCHECK_PRIVATE_DIR": str(self.root / "private")},
        )
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()
        self.tmp.cleanup()

    def request(self, request_type, subject_ref):
        return compliance_store.create_rights_request(
            {"type": request_type, "subjectRef": subject_ref},
            self.compliance_db,
        )

    @patch.object(rights.mercure_rights, "contact_snapshot")
    def test_provider_failure_is_partial_and_retry_can_complete(self, snapshot):
        subject_ref = "account:client-1"
        request = self.request("restriction", subject_ref)
        snapshot.side_effect = [
            RuntimeError("provider unavailable"),
            {
                "provider": "mercure",
                "subject": {"clientKind": "account", "clientId": "client-1"},
                "contact": {
                    "email": "client@example.fr",
                    "telephone": "+33102030405",
                },
                "coverage": {
                    "contact": True,
                    "vehicles": False,
                    "appointments": False,
                    "billing": False,
                },
                "partial": True,
            },
        ]

        partial = rights.execute(
            request["id"],
            subject_ref,
            adapter="privacy_suppression",
            db_path=self.compliance_db,
        )
        self.assertFalse(partial["identityResolutionComplete"])
        self.assertTrue(partial["providerContactRequired"])
        self.assertFalse(partial["providerContactResolved"])
        self.assertTrue(
            privacy_suppression.is_suppressed(
                "mercure_account",
                "client-1",
                "all_processing",
                db_path=self.compliance_db,
            )
        )
        self.assertEqual(
            [row["action"] for row in rights.audit_rows(self.compliance_db)],
            ["suppress_partial"],
        )

        complete = rights.execute(
            request["id"],
            subject_ref,
            adapter="privacy_suppression",
            db_path=self.compliance_db,
        )
        self.assertTrue(complete["identityResolutionComplete"])
        self.assertTrue(complete["providerContactResolved"])
        self.assertTrue(
            privacy_suppression.is_suppressed(
                "email",
                "client@example.fr",
                "all_processing",
                db_path=self.compliance_db,
            )
        )
        self.assertTrue(
            privacy_suppression.is_suppressed(
                "phone",
                "+33102030405",
                "all_processing",
                db_path=self.compliance_db,
            )
        )
        actions = {row["action"] for row in rights.audit_rows(self.compliance_db)}
        self.assertEqual(actions, {"suppress_partial", "suppress_complete"})

        with self.assertRaisesRegex(RuntimeError, "adaptateur déjà exécuté"):
            rights.execute(
                request["id"],
                subject_ref,
                adapter="privacy_suppression",
                db_path=self.compliance_db,
            )
        self.assertEqual(snapshot.call_count, 2)
        audit_text = repr(rights.audit_rows(self.compliance_db))
        self.assertNotIn(subject_ref, audit_text)
        self.assertNotIn("client@example.fr", audit_text)
        self.assertNotIn("+33102030405", audit_text)

    @patch.object(rights.mobile_devices, "registered_vehicle_bindings")
    @patch.object(rights.mercure_rights, "contact_snapshot")
    def test_mobile_binding_failure_stays_retryable_without_provider_lookup(
        self,
        snapshot,
        bindings,
    ):
        installation_id = "60cf7ccf-4297-41f4-b76b-c0bd44dbe3d1"
        request = self.request("erasure", installation_id)
        bindings.side_effect = [RuntimeError("mobile store unavailable"), []]

        partial = rights.execute(
            request["id"],
            installation_id,
            adapter="privacy_suppression",
            db_path=self.compliance_db,
        )
        self.assertFalse(partial["identityResolutionComplete"])
        self.assertTrue(partial["mobileBindingsRequired"])
        self.assertFalse(partial["mobileBindingsResolved"])
        self.assertFalse(partial["providerContactRequired"])
        snapshot.assert_not_called()

        complete = rights.execute(
            request["id"],
            installation_id,
            adapter="privacy_suppression",
            db_path=self.compliance_db,
        )
        self.assertTrue(complete["identityResolutionComplete"])
        self.assertTrue(complete["mobileBindingsResolved"])
        self.assertFalse(complete["providerContactRequired"])
        self.assertEqual(
            {row["action"] for row in rights.audit_rows(self.compliance_db)},
            {"suppress_partial", "suppress_complete"},
        )

    @patch.object(rights.mercure_rights, "contact_snapshot")
    def test_direct_email_suppression_completes_without_provider_dependency(self, snapshot):
        email = "Client@Example.FR"
        request = self.request("objection", email)
        result = rights.execute(
            request["id"],
            email,
            adapter="privacy_suppression",
            purpose="direct_marketing_email",
            db_path=self.compliance_db,
        )
        self.assertTrue(result["identityResolutionComplete"])
        self.assertFalse(result["providerContactRequired"])
        self.assertTrue(result["providerContactResolved"])
        snapshot.assert_not_called()
        audit = rights.audit_rows(self.compliance_db)
        self.assertEqual(audit[0]["action"], "suppress_complete")
        self.assertTrue(
            privacy_suppression.is_suppressed(
                "email",
                "client@example.fr",
                "direct_marketing_email",
                db_path=self.compliance_db,
            )
        )

    def test_completed_erasure_can_resume_downstream_without_second_audit(self):
        email = "client@example.fr"
        request = self.request("erasure", email)

        first = rights.execute(
            request["id"],
            email,
            adapter="privacy_suppression",
            db_path=self.compliance_db,
        )
        self.assertTrue(first["identityResolutionComplete"])
        self.assertFalse(first.get("recoveredFromCompletedAudit", False))
        audit_before = rights.audit_rows(self.compliance_db)
        self.assertEqual(len(audit_before), 1)
        self.assertEqual(audit_before[0]["action"], "suppress_complete")

        with self.assertRaisesRegex(RuntimeError, "adaptateur déjà exécuté"):
            rights.execute(
                request["id"],
                email,
                adapter="privacy_suppression",
                db_path=self.compliance_db,
            )

        resumed = rights.execute(
            request["id"],
            email,
            adapter="privacy_suppression",
            db_path=self.compliance_db,
            resume_completed_erasure=True,
        )
        self.assertTrue(resumed["recoveredFromCompletedAudit"])
        self.assertEqual(resumed["requestType"], "erasure")
        self.assertEqual(resumed["purposes"], ["all_processing"])
        self.assertEqual(resumed["executionId"], first["executionId"])
        self.assertEqual(rights.audit_rows(self.compliance_db), audit_before)

    def test_completed_non_erasure_is_not_resumable_as_erasure(self):
        email = "client@example.fr"
        request = self.request("objection", email)
        rights.execute(
            request["id"],
            email,
            adapter="privacy_suppression",
            purpose="direct_marketing_email",
            db_path=self.compliance_db,
        )

        with self.assertRaisesRegex(RuntimeError, "adaptateur déjà exécuté"):
            rights.execute(
                request["id"],
                email,
                adapter="privacy_suppression",
                purpose="direct_marketing_email",
                db_path=self.compliance_db,
                resume_completed_erasure=True,
            )
        self.assertEqual(len(rights.audit_rows(self.compliance_db)), 1)

    def test_capability_exposes_privacy_suppression_retry_completion_action(self):
        state = rights.capability(self.compliance_db)
        self.assertEqual(
            state["retryablePartialAdapters"]["privacy_suppression"],
            "suppress_complete",
        )


if __name__ == "__main__":
    unittest.main()
