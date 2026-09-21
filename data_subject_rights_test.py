import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import compliance_store
import data_subject_rights as rights
import mobile_devices


class DataSubjectRightsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.compliance_db = self.root / "compliance.sqlite3"
        self.old_mobile_dir, self.old_mobile_db = mobile_devices.DATA_DIR, mobile_devices.DB
        mobile_devices.DATA_DIR = self.root / "mobile"
        mobile_devices.DB = mobile_devices.DATA_DIR / "mobile.sqlite3"
        mobile_devices.init_db()
        self.installation_id = "60cf7ccf-4297-41f4-b76b-c0bd44dbe3d1"
        self.secret = "A" * 43
        self.device_token = "ab" * 32
        mobile_devices.register({
            "installationId": self.installation_id,
            "registrationSecret": self.secret,
            "deviceToken": self.device_token,
            "environment": "sandbox",
        })
        mobile_devices.sync_deadlines({
            "installationId": self.installation_id,
            "registrationSecret": self.secret,
            "deadlines": [{
                "deadlineId": "e62c0b27-2141-4f5c-b2f4-1e458aa6a6ca",
                "dueDate": "2027-01-15",
            }],
        })
        with mobile_devices.connect() as db:
            db.execute(
                """INSERT INTO mobile_vehicle_binding(
                     binding_id,installation_id,vehicle_id,client_kind,client_id,created_at,updated_at
                   ) VALUES(?,?,?,?,?,?,?)""",
                (
                    "binding-test",
                    self.installation_id,
                    "vehicle-1",
                    "account",
                    "client-1",
                    "2026-09-21T00:00:00+00:00",
                    "2026-09-21T00:00:00+00:00",
                ),
            )

    def tearDown(self):
        mobile_devices.DATA_DIR, mobile_devices.DB = self.old_mobile_dir, self.old_mobile_db
        self.tmp.cleanup()

    def request(self, request_type, subject_ref=None):
        return compliance_store.create_rights_request(
            {"type": request_type, "subjectRef": subject_ref or self.installation_id},
            self.compliance_db,
        )

    def test_access_export_reverifies_subject_and_never_exports_mobile_secrets(self):
        request = self.request("access")
        result = rights.execute(
            request["id"],
            self.installation_id,
            adapter="mobile_installation",
            db_path=self.compliance_db,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["requestType"], "access")
        self.assertEqual(result["format"], "application/json")
        self.assertEqual(result["requestStatus"], "in_progress")
        self.assertFalse(result["requestComplete"])
        self.assertEqual(result["data"]["installationId"], self.installation_id)
        self.assertTrue(result["data"]["device"]["pushTokenPresent"])
        self.assertEqual(len(result["data"]["deadlines"]), 1)
        self.assertEqual(len(result["data"]["vehicleBindings"]), 1)
        serialized = str(result)
        self.assertNotIn(self.device_token, serialized)
        self.assertNotIn(self.secret, serialized)
        stored = compliance_store.rights_requests(self.compliance_db)
        self.assertEqual(stored[0]["status"], "in_progress")
        self.assertEqual(stored[0]["closedAt"], "")
        audit = rights.audit_rows(self.compliance_db)
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["action"], "export")
        self.assertEqual(len(audit[0]["evidenceHash"]), 64)
        self.assertNotIn(self.installation_id, str(audit[0]))

    def test_wrong_subject_reference_is_refused_without_closing_request(self):
        request = self.request("erasure")
        wrong = "61cf7ccf-4297-41f4-b76b-c0bd44dbe3d1"
        with self.assertRaises(PermissionError):
            rights.execute(
                request["id"],
                wrong,
                adapter="mobile_installation",
                db_path=self.compliance_db,
            )
        self.assertEqual(compliance_store.rights_requests(self.compliance_db)[0]["status"], "open")
        self.assertEqual(rights.audit_rows(self.compliance_db), [])
        self.assertEqual(mobile_devices.status()["total"], 1)

    def test_erasure_removes_only_installation_bound_mobile_records_and_records_evidence(self):
        request = self.request("erasure")
        result = rights.execute(
            request["id"],
            self.installation_id,
            adapter="mobile_installation",
            db_path=self.compliance_db,
        )
        self.assertEqual(result["removed"], {
            "deviceRecords": 1,
            "deadlineRecords": 1,
            "vehicleBindingRecords": 1,
        })
        self.assertEqual(result["requestStatus"], "in_progress")
        self.assertFalse(result["requestComplete"])
        self.assertEqual(compliance_store.rights_requests(self.compliance_db)[0]["status"], "in_progress")
        self.assertEqual(mobile_devices.status()["total"], 0)
        with mobile_devices.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) n FROM mobile_deadline").fetchone()["n"], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) n FROM mobile_vehicle_binding").fetchone()["n"], 0)
        audit = rights.audit_rows(self.compliance_db)
        self.assertEqual(audit[0]["requestType"], "erasure")
        self.assertEqual(audit[0]["action"], "erase")

    def test_duplicate_adapter_execution_is_refused_without_second_audit(self):
        request = self.request("access")
        rights.execute(
            request["id"],
            self.installation_id,
            adapter="mobile_installation",
            db_path=self.compliance_db,
        )
        with self.assertRaisesRegex(RuntimeError, "adaptateur déjà exécuté"):
            rights.execute(
                request["id"],
                self.installation_id,
                adapter="mobile_installation",
                db_path=self.compliance_db,
            )
        self.assertEqual(compliance_store.rights_requests(self.compliance_db)[0]["status"], "in_progress")
        self.assertEqual(len(rights.audit_rows(self.compliance_db)), 1)

    def test_portability_returns_machine_readable_export(self):
        request = self.request("portability")
        result = rights.execute(
            request["id"],
            self.installation_id,
            adapter="mobile_installation",
            db_path=self.compliance_db,
        )
        self.assertEqual(result["format"], "application/json")
        self.assertEqual(result["data"]["device"]["environment"], "sandbox")
        self.assertFalse(result["requestComplete"])

    @patch.object(rights.mercure_rights, "contact_snapshot")
    def test_mercure_contact_access_is_partial_and_audit_does_not_expose_subject_data(self, snapshot):
        subject_ref = "account:12"
        snapshot.return_value = {
            "provider": "mercure",
            "subject": {"clientKind": "account", "clientId": "12"},
            "contact": {"email": "client@example.fr", "telephone": "+33102030405"},
            "coverage": {"contact": True, "vehicles": False, "appointments": False, "billing": False},
            "partial": True,
        }
        request = self.request("access", subject_ref)
        result = rights.execute(
            request["id"],
            subject_ref,
            adapter="mercure_customer_contact",
            db_path=self.compliance_db,
        )
        snapshot.assert_called_once_with(subject_ref)
        self.assertEqual(result["format"], "application/json")
        self.assertEqual(result["data"]["provider"], "mercure")
        self.assertTrue(result["data"]["partial"])
        self.assertEqual(result["requestStatus"], "in_progress")
        self.assertFalse(result["requestComplete"])
        audit = rights.audit_rows(self.compliance_db)
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["adapter"], "mercure_customer_contact")
        self.assertEqual(audit[0]["action"], "export")
        exposed_audit = repr(audit)
        self.assertNotIn(subject_ref, exposed_audit)
        self.assertNotIn("client@example.fr", exposed_audit)
        self.assertNotIn("+33102030405", exposed_audit)

    @patch.object(rights.mercure_rights, "contact_snapshot")
    def test_unbound_cross_store_subject_is_refused_before_provider_call(self, snapshot):
        request = self.request("access")
        with self.assertRaises(PermissionError):
            rights.execute(
                request["id"],
                "account:client-1",
                adapter="mercure_customer_contact",
                db_path=self.compliance_db,
            )
        snapshot.assert_not_called()
        self.assertEqual(rights.audit_rows(self.compliance_db), [])
        self.assertEqual(compliance_store.rights_requests(self.compliance_db)[0]["status"], "open")

    @patch.object(rights.mercure_rights, "contact_snapshot")
    def test_verified_mobile_binding_allows_same_request_to_execute_mercure(self, snapshot):
        subject_ref = "account:client-1"
        request = self.request("access")
        binding = rights.bind_mercure_from_mobile(
            request["id"],
            self.installation_id,
            subject_ref,
            self.compliance_db,
        )
        self.assertTrue(binding["bound"])
        self.assertEqual(binding["provenance"], "mobile_vehicle_binding")
        self.assertFalse(binding["rawSubjectReferencePersisted"])
        self.assertNotIn(self.installation_id, repr(binding))
        self.assertNotIn(subject_ref, repr(binding))
        binding_rows = rights.rights_subject_bindings.rows(self.compliance_db)
        self.assertEqual(len(binding_rows), 1)
        self.assertEqual(binding_rows[0]["adapter"], "mercure_customer_contact")
        self.assertEqual(len(binding_rows[0]["evidenceHash"]), 64)
        self.assertNotIn(self.installation_id, repr(binding_rows))
        self.assertNotIn(subject_ref, repr(binding_rows))

        rights.execute(
            request["id"],
            self.installation_id,
            adapter="mobile_installation",
            db_path=self.compliance_db,
        )
        snapshot.return_value = {
            "provider": "mercure",
            "subject": {"clientKind": "account", "clientId": "client-1"},
            "contact": {"email": "client@example.fr", "telephone": "+33102030405"},
            "coverage": {"contact": True, "vehicles": False, "appointments": False, "billing": False},
            "partial": True,
        }
        result = rights.execute(
            request["id"],
            subject_ref,
            adapter="mercure_customer_contact",
            db_path=self.compliance_db,
        )
        snapshot.assert_called_once_with(subject_ref)
        self.assertTrue(result["ok"])
        self.assertFalse(result["requestComplete"])
        self.assertEqual(result["requestStatus"], "in_progress")
        self.assertEqual(compliance_store.rights_requests(self.compliance_db)[0]["status"], "in_progress")
        audit = rights.audit_rows(self.compliance_db)
        self.assertEqual(len(audit), 2)
        self.assertEqual(
            {row["adapter"] for row in audit},
            {"mobile_installation", "mercure_customer_contact"},
        )

    def test_binding_rejects_unproven_mercure_customer(self):
        request = self.request("access")
        with self.assertRaisesRegex(PermissionError, "liaison Mercure non prouvée"):
            rights.bind_mercure_from_mobile(
                request["id"],
                self.installation_id,
                "account:other-client",
                self.compliance_db,
            )
        self.assertEqual(rights.rights_subject_bindings.rows(self.compliance_db), [])

    def test_binding_rejects_wrong_primary_installation(self):
        request = self.request("access")
        wrong_installation = "61cf7ccf-4297-41f4-b76b-c0bd44dbe3d1"
        with self.assertRaisesRegex(PermissionError, "référence du demandeur refusée"):
            rights.bind_mercure_from_mobile(
                request["id"],
                wrong_installation,
                "account:client-1",
                self.compliance_db,
            )
        self.assertEqual(rights.rights_subject_bindings.rows(self.compliance_db), [])

    @patch.object(rights.mercure_rights, "contact_snapshot")
    def test_mercure_erasure_remains_unimplemented_and_does_not_call_provider(self, snapshot):
        subject_ref = "free:34"
        request = self.request("erasure", subject_ref)
        with self.assertRaises(NotImplementedError):
            rights.execute(
                request["id"],
                subject_ref,
                adapter="mercure_customer_contact",
                db_path=self.compliance_db,
            )
        snapshot.assert_not_called()
        self.assertEqual(compliance_store.rights_requests(self.compliance_db)[0]["status"], "open")
        self.assertEqual(rights.audit_rows(self.compliance_db), [])

    def test_unimplemented_right_stays_open(self):
        request = self.request("rectification")
        with self.assertRaises(NotImplementedError):
            rights.execute(
                request["id"],
                self.installation_id,
                adapter="mobile_installation",
                db_path=self.compliance_db,
            )
        self.assertEqual(compliance_store.rights_requests(self.compliance_db)[0]["status"], "open")
        self.assertEqual(rights.audit_rows(self.compliance_db), [])

    def test_capability_is_explicitly_partial_and_fail_closed(self):
        state = rights.capability(self.compliance_db)
        self.assertFalse(state["bound"])
        self.assertTrue(state["partial"])
        self.assertEqual(
            state["supportedAdapters"]["mobile_installation"],
            ["access", "portability", "erasure"],
        )
        self.assertEqual(
            state["supportedAdapters"]["mercure_customer_contact"],
            ["access", "portability"],
        )
        self.assertFalse(state["rawSubjectReferencePersisted"])
        self.assertTrue(state["subjectReferenceReverifiedAtExecution"])
        self.assertTrue(state["crossStoreSubjectBindings"])
        self.assertEqual(state["subjectBindingProvenance"], ["mobile_vehicle_binding"])
        self.assertFalse(state["partialExecutionClosesRequest"])
        self.assertIn("mercure", state["partialSystemAdapters"])
        self.assertIn("mercure", state["remainingSystemAdapters"])


if __name__ == "__main__":
    unittest.main()
