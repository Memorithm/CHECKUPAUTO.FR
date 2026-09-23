from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import analytics_store as analytics
import compliance_store
import data_subject_rights
import mobile_devices
import referral_wallet_lifecycle
import rights_execution_dispatch


INSTALLATION_ID = "60cf7ccf-4297-41f4-b76b-c0bd44dbe3d1"
SECRET = "A" * 43
TOKEN = "ab" * 32


class MobileDsarErasureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.compliance_db = self.root / "compliance.sqlite3"

        self.analytics_patch = mock.patch.object(
            analytics,
            "DB",
            self.root / "analytics.sqlite3",
        )
        self.analytics_patch.start()
        self.old_mobile_dir, self.old_mobile_db = mobile_devices.DATA_DIR, mobile_devices.DB
        mobile_devices.DATA_DIR = self.root / "mobile"
        mobile_devices.DB = mobile_devices.DATA_DIR / "mobile.sqlite3"
        mobile_devices.init_db()
        mobile_devices.register(
            {
                "installationId": INSTALLATION_ID,
                "registrationSecret": SECRET,
                "deviceToken": TOKEN,
                "environment": "sandbox",
            }
        )
        mobile_devices.sync_deadlines(
            {
                "installationId": INSTALLATION_ID,
                "registrationSecret": SECRET,
                "deadlines": [
                    {
                        "deadlineId": "e62c0b27-2141-4f5c-b2f4-1e458aa6a6ca",
                        "dueDate": "2027-01-15",
                    }
                ],
            }
        )
        with mobile_devices.connect() as db:
            db.execute(
                """INSERT INTO mobile_vehicle_binding(
                     binding_id,installation_id,vehicle_id,client_kind,client_id,created_at,updated_at
                   ) VALUES(?,?,?,?,?,?,?)""",
                (
                    "binding-test",
                    INSTALLATION_ID,
                    "vehicle-1",
                    "account",
                    "client-1",
                    "2026-09-23T00:00:00+00:00",
                    "2026-09-23T00:00:00+00:00",
                ),
            )
        self.request = compliance_store.create_rights_request(
            {"type": "erasure", "subjectRef": INSTALLATION_ID},
            self.compliance_db,
        )

    def tearDown(self):
        mobile_devices.DATA_DIR, mobile_devices.DB = self.old_mobile_dir, self.old_mobile_db
        self.analytics_patch.stop()
        self.tmp.cleanup()

    def payload(self):
        return {
            "id": self.request["id"],
            "subjectRef": INSTALLATION_ID,
            "adapter": "mobile_installation",
        }

    def test_dispatch_erasure_persists_receipt_before_compliance_audit(self):
        result = rights_execution_dispatch.execute(self.payload(), self.compliance_db)
        self.assertEqual(
            result["removed"],
            {
                "deviceRecords": 1,
                "deadlineRecords": 1,
                "vehicleBindingRecords": 1,
            },
        )
        self.assertFalse(result["recoveredFromReceipt"])
        self.assertEqual(len(result["mobileErasureEvidenceHash"]), 64)
        self.assertEqual(mobile_devices.status()["total"], 0)

        digest = hashlib.sha256(INSTALLATION_ID.encode("utf-8")).hexdigest()
        receipt = referral_wallet_lifecycle.mobile_erasure_receipt_by_subject_hash(digest)
        self.assertIsNotNone(receipt)
        self.assertEqual(receipt["evidenceHash"], result["mobileErasureEvidenceHash"])
        self.assertEqual(receipt["removed"], result["removed"])
        audit = data_subject_rights.audit_rows(self.compliance_db)
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["action"], "erase")
        self.assertNotIn(INSTALLATION_ID, repr(audit))
        self.assertNotIn(TOKEN, repr(audit))
        self.assertNotIn(SECRET, repr(audit))

    def test_direct_executor_uses_the_same_recoverable_receipt_boundary(self):
        result = data_subject_rights.execute(
            self.request["id"],
            INSTALLATION_ID,
            adapter="mobile_installation",
            db_path=self.compliance_db,
        )
        self.assertFalse(result["recoveredFromReceipt"])
        self.assertEqual(len(result["mobileErasureEvidenceHash"]), 64)
        self.assertEqual(mobile_devices.status()["total"], 0)

        digest = hashlib.sha256(INSTALLATION_ID.encode("utf-8")).hexdigest()
        receipt = referral_wallet_lifecycle.mobile_erasure_receipt_by_subject_hash(digest)
        self.assertIsNotNone(receipt)
        self.assertEqual(receipt["evidenceHash"], result["mobileErasureEvidenceHash"])
        self.assertEqual(receipt["removed"], result["removed"])
        audit = data_subject_rights.audit_rows(self.compliance_db)
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["action"], "erase")

    def test_retry_recovers_committed_receipt_after_audit_failure(self):
        with mock.patch.object(
            data_subject_rights,
            "_audit_execution",
            side_effect=RuntimeError("forced audit failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "forced audit failure"):
                rights_execution_dispatch.execute(self.payload(), self.compliance_db)

        self.assertEqual(mobile_devices.status()["total"], 0)
        self.assertEqual(data_subject_rights.audit_rows(self.compliance_db), [])
        digest = hashlib.sha256(INSTALLATION_ID.encode("utf-8")).hexdigest()
        committed = referral_wallet_lifecycle.mobile_erasure_receipt_by_subject_hash(digest)
        self.assertIsNotNone(committed)
        with mobile_devices.connect() as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) n FROM mobile_erasure_receipt").fetchone()["n"],
                1,
            )

        retry = rights_execution_dispatch.execute(self.payload(), self.compliance_db)
        self.assertTrue(retry["recoveredFromReceipt"])
        self.assertEqual(retry["mobileErasureEvidenceHash"], committed["evidenceHash"])
        self.assertEqual(retry["removed"], committed["removed"])
        self.assertEqual(len(data_subject_rights.audit_rows(self.compliance_db)), 1)
        with mobile_devices.connect() as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) n FROM mobile_erasure_receipt").fetchone()["n"],
                1,
            )


if __name__ == "__main__":
    unittest.main()
