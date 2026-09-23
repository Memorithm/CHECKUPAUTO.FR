import tempfile
import unittest
from pathlib import Path
from unittest import mock

import compliance_store
import data_subject_rights
import mobile_devices
import rights_rectification as rectification


class RightsRectificationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.compliance_db = self.root / "compliance.sqlite3"
        self.old_mobile_dir, self.old_mobile_db = mobile_devices.DATA_DIR, mobile_devices.DB
        mobile_devices.DATA_DIR = self.root / "mobile"
        mobile_devices.DB = mobile_devices.DATA_DIR / "mobile.sqlite3"
        self.installation_id = "60cf7ccf-4297-41f4-b76b-c0bd44dbe3d1"
        self.secret = "A" * 43
        self.device_deadline = "e62c0b27-2141-4f5c-b2f4-1e458aa6a6ca"
        self.authoritative_deadline = "72dff11e-12b8-4de3-aa8e-26db3228075b"
        mobile_devices.register({
            "installationId": self.installation_id,
            "registrationSecret": self.secret,
            "deviceToken": "ab" * 32,
            "environment": "sandbox",
        })
        mobile_devices.sync_deadlines({
            "installationId": self.installation_id,
            "registrationSecret": self.secret,
            "deadlines": [{"deadlineId": self.device_deadline, "dueDate": "2027-01-15"}],
        })
        mobile_devices.sync_authoritative_deadlines(
            self.installation_id,
            [{"deadlineId": self.authoritative_deadline, "dueDate": "2027-06-15"}],
        )

    def tearDown(self):
        mobile_devices.DATA_DIR, mobile_devices.DB = self.old_mobile_dir, self.old_mobile_db
        self.tmp.cleanup()

    def request(self):
        return compliance_store.create_rights_request(
            {"type": "rectification", "subjectRef": self.installation_id},
            self.compliance_db,
        )

    def due_date(self, deadline_id):
        with mobile_devices.connect() as db:
            row = db.execute(
                "SELECT due_date,source FROM mobile_deadline WHERE installation_id=? AND deadline_id=?",
                (self.installation_id, deadline_id),
            ).fetchone()
        return str(row["due_date"]), str(row["source"])

    def rectification_receipts(self):
        with mobile_devices.connect() as db:
            exists = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='mobile_rectification_receipt'"
            ).fetchone()
            if not exists:
                return []
            return [dict(row) for row in db.execute(
                """SELECT request_hash,subject_ref_hash,correction_hash,executed_at
                   FROM mobile_rectification_receipt ORDER BY executed_at"""
            )]

    def test_rectifies_only_existing_device_deadline_and_audits_hash_only(self):
        request = self.request()
        result = rectification.execute(
            request["id"],
            self.installation_id,
            {"deadlineId": self.device_deadline, "dueDate": "2027-02-20"},
            self.compliance_db,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["adapter"], rectification.ADAPTER)
        self.assertEqual(result["field"], rectification.FIELD)
        self.assertEqual(result["source"], mobile_devices.DEVICE_DEADLINE_SOURCE)
        self.assertFalse(result["recoveredFromReceipt"])
        self.assertFalse(result["requestComplete"])
        self.assertEqual(self.due_date(self.device_deadline), ("2027-02-20", "device"))
        self.assertEqual(self.due_date(self.authoritative_deadline), ("2027-06-15", "mercure"))
        rows = data_subject_rights.audit_rows(self.compliance_db)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["action"], "rectify")
        self.assertEqual(rows[0]["adapter"], rectification.ADAPTER)
        serialized = repr(rows)
        self.assertNotIn(self.installation_id, serialized)
        self.assertNotIn(self.device_deadline, serialized)
        self.assertNotIn("2027-02-20", serialized)
        receipts = self.rectification_receipts()
        self.assertEqual(len(receipts), 1)
        serialized_receipts = repr(receipts)
        self.assertNotIn(request["id"], serialized_receipts)
        self.assertNotIn(self.installation_id, serialized_receipts)
        self.assertNotIn(self.device_deadline, serialized_receipts)
        self.assertNotIn("2027-02-20", serialized_receipts)
        stored = compliance_store.rights_requests(self.compliance_db)[0]
        self.assertEqual(stored["status"], "in_progress")
        self.assertEqual(stored["closedAt"], "")

    def test_authoritative_deadline_fails_closed_without_audit_or_mutation(self):
        request = self.request()
        with self.assertRaisesRegex(PermissionError, "autoritaire"):
            rectification.execute(
                request["id"],
                self.installation_id,
                {"deadlineId": self.authoritative_deadline, "dueDate": "2028-01-01"},
                self.compliance_db,
            )
        self.assertEqual(self.due_date(self.authoritative_deadline), ("2027-06-15", "mercure"))
        self.assertEqual(data_subject_rights.audit_rows(self.compliance_db), [])
        self.assertEqual(self.rectification_receipts(), [])
        self.assertEqual(compliance_store.rights_requests(self.compliance_db)[0]["status"], "open")

    def test_wrong_primary_subject_is_rejected_before_mobile_mutation(self):
        request = self.request()
        with self.assertRaisesRegex(PermissionError, "demandeur"):
            rectification.execute(
                request["id"],
                "61cf7ccf-4297-41f4-b76b-c0bd44dbe3d1",
                {"deadlineId": self.device_deadline, "dueDate": "2028-01-01"},
                self.compliance_db,
            )
        self.assertEqual(self.due_date(self.device_deadline), ("2027-01-15", "device"))
        self.assertEqual(data_subject_rights.audit_rows(self.compliance_db), [])

    def test_correction_shape_is_strict_and_duplicate_execution_is_refused(self):
        request = self.request()
        with self.assertRaisesRegex(ValueError, "correction"):
            rectification.execute(
                request["id"],
                self.installation_id,
                {"deadlineId": self.device_deadline, "dueDate": "2028-01-01", "note": "x"},
                self.compliance_db,
            )
        rectification.execute(
            request["id"],
            self.installation_id,
            {"deadlineId": self.device_deadline, "dueDate": "2028-01-01"},
            self.compliance_db,
        )
        with self.assertRaisesRegex(RuntimeError, "déjà exécuté"):
            rectification.execute(
                request["id"],
                self.installation_id,
                {"deadlineId": self.device_deadline, "dueDate": "2029-01-01"},
                self.compliance_db,
            )
        self.assertEqual(self.due_date(self.device_deadline), ("2028-01-01", "device"))
        self.assertEqual(len(data_subject_rights.audit_rows(self.compliance_db)), 1)
        self.assertEqual(len(self.rectification_receipts()), 1)

    def test_audit_failure_after_mobile_commit_recovers_from_minimized_receipt(self):
        request = self.request()
        correction = {"deadlineId": self.device_deadline, "dueDate": "2027-03-20"}
        with mock.patch.object(
            rectification.rights,
            "_audit_execution",
            side_effect=RuntimeError("simulated compliance audit failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "simulated compliance audit failure"):
                rectification.execute(
                    request["id"],
                    self.installation_id,
                    correction,
                    self.compliance_db,
                )

        self.assertEqual(self.due_date(self.device_deadline), ("2027-03-20", "device"))
        self.assertEqual(data_subject_rights.audit_rows(self.compliance_db), [])
        receipts = self.rectification_receipts()
        self.assertEqual(len(receipts), 1)
        serialized = repr(receipts)
        self.assertNotIn(request["id"], serialized)
        self.assertNotIn(self.installation_id, serialized)
        self.assertNotIn(self.device_deadline, serialized)
        self.assertNotIn("2027-03-20", serialized)

        recovered = rectification.execute(
            request["id"],
            self.installation_id,
            correction,
            self.compliance_db,
        )
        self.assertTrue(recovered["ok"])
        self.assertTrue(recovered["recoveredFromReceipt"])
        self.assertEqual(self.due_date(self.device_deadline), ("2027-03-20", "device"))
        self.assertEqual(len(self.rectification_receipts()), 1)
        self.assertEqual(len(data_subject_rights.audit_rows(self.compliance_db)), 1)

    def test_recovery_refuses_different_correction_after_pre_audit_crash(self):
        request = self.request()
        first = {"deadlineId": self.device_deadline, "dueDate": "2027-04-20"}
        with mock.patch.object(
            rectification.rights,
            "_audit_execution",
            side_effect=RuntimeError("simulated compliance audit failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "simulated compliance audit failure"):
                rectification.execute(
                    request["id"],
                    self.installation_id,
                    first,
                    self.compliance_db,
                )

        with self.assertRaisesRegex(RuntimeError, "contradictoire"):
            rectification.execute(
                request["id"],
                self.installation_id,
                {"deadlineId": self.device_deadline, "dueDate": "2027-05-20"},
                self.compliance_db,
            )
        self.assertEqual(self.due_date(self.device_deadline), ("2027-04-20", "device"))
        self.assertEqual(len(self.rectification_receipts()), 1)
        self.assertEqual(data_subject_rights.audit_rows(self.compliance_db), [])

    def test_recovery_refuses_receipt_after_later_device_change(self):
        request = self.request()
        correction = {"deadlineId": self.device_deadline, "dueDate": "2027-04-21"}
        with mock.patch.object(
            rectification.rights,
            "_audit_execution",
            side_effect=RuntimeError("simulated compliance audit failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "simulated compliance audit failure"):
                rectification.execute(
                    request["id"],
                    self.installation_id,
                    correction,
                    self.compliance_db,
                )

        mobile_devices.sync_deadlines({
            "installationId": self.installation_id,
            "registrationSecret": self.secret,
            "deadlines": [{"deadlineId": self.device_deadline, "dueDate": "2027-09-01"}],
        })

        with self.assertRaisesRegex(RuntimeError, "obsolète"):
            rectification.execute(
                request["id"],
                self.installation_id,
                correction,
                self.compliance_db,
            )
        self.assertEqual(self.due_date(self.device_deadline), ("2027-09-01", "device"))
        self.assertEqual(len(self.rectification_receipts()), 1)
        self.assertEqual(data_subject_rights.audit_rows(self.compliance_db), [])

    def test_recovery_refuses_same_value_resync_as_newer_generation(self):
        request = self.request()
        correction = {"deadlineId": self.device_deadline, "dueDate": "2027-04-22"}
        with mock.patch.object(
            rectification.rights,
            "_audit_execution",
            side_effect=RuntimeError("simulated compliance audit failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "simulated compliance audit failure"):
                rectification.execute(
                    request["id"],
                    self.installation_id,
                    correction,
                    self.compliance_db,
                )

        mobile_devices.sync_deadlines({
            "installationId": self.installation_id,
            "registrationSecret": self.secret,
            "deadlines": [{"deadlineId": self.device_deadline, "dueDate": "2027-04-22"}],
        })

        with self.assertRaisesRegex(RuntimeError, "obsolète"):
            rectification.execute(
                request["id"],
                self.installation_id,
                correction,
                self.compliance_db,
            )
        self.assertEqual(self.due_date(self.device_deadline), ("2027-04-22", "device"))
        self.assertEqual(len(self.rectification_receipts()), 1)
        self.assertEqual(data_subject_rights.audit_rows(self.compliance_db), [])

    def test_capability_remains_partial_and_refuses_authoritative_sources(self):
        state = rectification.capability()
        self.assertFalse(state["bound"])
        self.assertTrue(state["partial"])
        self.assertEqual(state["supportedFields"], ["device_deadline_due_date"])
        self.assertFalse(state["authoritativeSourcesMutable"])
        self.assertFalse(state["rawSubjectReferencePersisted"])
        self.assertTrue(state["crashRecoverable"])
        self.assertTrue(state["recoveryRequiresCurrentState"])
        self.assertFalse(state["receiptStoresRawSubject"])


if __name__ == "__main__":
    unittest.main()
