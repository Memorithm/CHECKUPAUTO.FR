import tempfile
import unittest
from pathlib import Path
from unittest import mock

import compliance_store
import data_subject_rights
import mobile_devices
import notification_broker
import notification_rectification
import rights_rectification


class RectificationNotificationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.compliance_db = self.root / "compliance.sqlite3"

        self.old_mobile_dir, self.old_mobile_db = mobile_devices.DATA_DIR, mobile_devices.DB
        mobile_devices.DATA_DIR = self.root / "mobile"
        mobile_devices.DB = mobile_devices.DATA_DIR / "mobile.sqlite3"

        self.old_notification_dir, self.old_notification_db = (
            notification_broker.DATA_DIR,
            notification_broker.DB,
        )
        notification_broker.DATA_DIR = self.root / "notifications"
        notification_broker.DB = notification_broker.DATA_DIR / "notification.sqlite3"

        self.installation_id = "60cf7ccf-4297-41f4-b76b-c0bd44dbe3d1"
        self.deadline_id = "e62c0b27-2141-4f5c-b2f4-1e458aa6a6ca"
        self.other_deadline_id = "72dff11e-12b8-4de3-aa8e-26db3228075b"
        self.secret = "A" * 43

    def tearDown(self):
        mobile_devices.DATA_DIR, mobile_devices.DB = self.old_mobile_dir, self.old_mobile_db
        notification_broker.DATA_DIR, notification_broker.DB = (
            self.old_notification_dir,
            self.old_notification_db,
        )
        self.tmp.cleanup()

    def _insert_delivery(
        self,
        key: str,
        reference: str,
        *,
        permanent_state: str = "open",
        failure_class: str = "permanent",
        status: str = "failed",
    ) -> None:
        notification_broker.init_db()
        with notification_broker.connect() as db:
            db.execute(
                """INSERT INTO notification_delivery(
                     idempotency_key,channel,category,reference,recipient_hash,status,
                     attempts,created_at,last_attempt_at,sent_at,last_error,
                     failure_class,incident_id,permanent_state,permanent_state_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    key,
                    "push",
                    "ct_due_reminder",
                    reference,
                    "a" * 64,
                    status,
                    1,
                    "2026-09-23T10:00:00+00:00",
                    "2026-09-23T10:00:00+00:00",
                    "2026-09-23T10:00:00+00:00" if status == "sent" else "",
                    "APNSError status=410 reason=Unregistered",
                    failure_class,
                    key.zfill(32)[-32:] if failure_class == "permanent" else "",
                    permanent_state if failure_class == "permanent" else "",
                    "2026-09-23T10:00:00+00:00" if failure_class == "permanent" else "",
                ),
            )

    def _delivery(self, key: str) -> dict:
        with notification_broker.connect() as db:
            row = db.execute(
                """SELECT status,failure_class,permanent_state,permanent_resolution
                   FROM notification_delivery WHERE idempotency_key=?""",
                (key,),
            ).fetchone()
        return dict(row)

    def _prepare_mobile(self) -> None:
        mobile_devices.register(
            {
                "installationId": self.installation_id,
                "registrationSecret": self.secret,
                "deviceToken": "ab" * 32,
                "environment": "sandbox",
            }
        )
        mobile_devices.sync_deadlines(
            {
                "installationId": self.installation_id,
                "registrationSecret": self.secret,
                "deadlines": [
                    {"deadlineId": self.deadline_id, "dueDate": "2027-01-15"}
                ],
            }
        )

    def test_reconcile_resolves_only_stale_open_or_acknowledged_permanent_incidents(self):
        self._insert_delivery(
            "1",
            f"mobile-ct:{self.deadline_id}:2027-01-15:j30",
            permanent_state="open",
        )
        self._insert_delivery(
            "2",
            f"mobile-ct:{self.deadline_id}:2027-01-16:j7",
            permanent_state="acknowledged",
        )
        self._insert_delivery(
            "3",
            f"mobile-ct:{self.deadline_id}:2027-02-20:j30",
            permanent_state="open",
        )
        self._insert_delivery(
            "4",
            f"mobile-ct:{self.other_deadline_id}:2027-01-15:j30",
            permanent_state="open",
        )
        self._insert_delivery(
            "5",
            f"mobile-ct:{self.deadline_id}:2027-01-15:j1",
            permanent_state="",
            failure_class="",
            status="sent",
        )

        result = notification_rectification.reconcile_mobile_deadline(
            self.deadline_id,
            "2027-02-20",
        )
        self.assertTrue(result["storePresent"])
        self.assertEqual(result["resolvedPermanentFailures"], 2)
        self.assertEqual(result["openStalePermanentFailures"], 0)
        self.assertEqual(self._delivery("1")["permanent_state"], "resolved")
        self.assertEqual(
            self._delivery("1")["permanent_resolution"],
            notification_rectification.PERMANENT_RESOLUTION,
        )
        self.assertEqual(self._delivery("2")["permanent_state"], "resolved")
        self.assertEqual(self._delivery("3")["permanent_state"], "open")
        self.assertEqual(self._delivery("4")["permanent_state"], "open")
        self.assertEqual(self._delivery("5")["status"], "sent")

        retry = notification_rectification.reconcile_mobile_deadline(
            self.deadline_id,
            "2027-02-20",
        )
        self.assertEqual(retry["resolvedPermanentFailures"], 2)
        self.assertEqual(retry["openStalePermanentFailures"], 0)

    def test_missing_broker_store_is_a_non_mutating_empty_reconciliation(self):
        self.assertFalse(notification_broker.DB.exists())
        result = notification_rectification.reconcile_mobile_deadline(
            self.deadline_id,
            "2027-02-20",
        )
        self.assertEqual(
            result,
            {
                "storePresent": False,
                "resolvedPermanentFailures": 0,
                "openStalePermanentFailures": 0,
            },
        )
        self.assertFalse(notification_broker.DB.exists())

    def test_rights_execution_reconciles_broker_before_compliance_audit(self):
        self._prepare_mobile()
        self._insert_delivery(
            "6",
            f"mobile-ct:{self.deadline_id}:2027-01-15:j30",
            permanent_state="open",
        )
        request = compliance_store.create_rights_request(
            {"type": "rectification", "subjectRef": self.installation_id},
            self.compliance_db,
        )

        result = rights_rectification.execute(
            request["id"],
            self.installation_id,
            {"deadlineId": self.deadline_id, "dueDate": "2027-02-20"},
            self.compliance_db,
        )
        self.assertTrue(result["notificationBrokerReconciled"])
        self.assertEqual(result["resolvedNotificationIncidents"], 1)
        self.assertEqual(self._delivery("6")["permanent_state"], "resolved")
        self.assertEqual(len(data_subject_rights.audit_rows(self.compliance_db)), 1)
        with mobile_devices.connect() as db:
            deadline = db.execute(
                """SELECT due_date FROM mobile_deadline
                   WHERE installation_id=? AND deadline_id=?""",
                (self.installation_id, self.deadline_id),
            ).fetchone()
        self.assertEqual(str(deadline["due_date"]), "2027-02-20")

    def test_broker_failure_after_mobile_commit_recovers_on_exact_retry(self):
        self._prepare_mobile()
        self._insert_delivery(
            "7",
            f"mobile-ct:{self.deadline_id}:2027-01-15:j30",
            permanent_state="open",
        )
        request = compliance_store.create_rights_request(
            {"type": "rectification", "subjectRef": self.installation_id},
            self.compliance_db,
        )
        correction = {"deadlineId": self.deadline_id, "dueDate": "2027-03-20"}

        with mock.patch.object(
            rights_rectification.notification_rectification,
            "reconcile_mobile_deadline",
            side_effect=RuntimeError("simulated broker failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "simulated broker failure"):
                rights_rectification.execute(
                    request["id"],
                    self.installation_id,
                    correction,
                    self.compliance_db,
                )

        self.assertEqual(data_subject_rights.audit_rows(self.compliance_db), [])
        self.assertEqual(self._delivery("7")["permanent_state"], "open")

        recovered = rights_rectification.execute(
            request["id"],
            self.installation_id,
            correction,
            self.compliance_db,
        )
        self.assertTrue(recovered["recoveredFromReceipt"])
        self.assertEqual(recovered["resolvedNotificationIncidents"], 1)
        self.assertEqual(self._delivery("7")["permanent_state"], "resolved")
        self.assertEqual(len(data_subject_rights.audit_rows(self.compliance_db)), 1)

    def test_capability_reports_broker_reconciliation_without_claiming_full_coverage(self):
        state = rights_rectification.capability()
        self.assertTrue(state["partial"])
        self.assertEqual(
            state["reconciledStores"],
            ["mobile_deadline", "notification_delivery"],
        )
        self.assertTrue(state["notificationBrokerStaleIncidentResolution"])
        self.assertFalse(state["sentNotificationHistoryMutable"])


if __name__ == "__main__":
    unittest.main()
