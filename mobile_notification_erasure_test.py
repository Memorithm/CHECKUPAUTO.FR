from __future__ import annotations

import datetime
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import analytics_store as analytics
import compliance_store
import data_subject_rights
import mobile_devices
import notification_broker
import notification_privacy
import privacy_suppression
import rights_execution_dispatch


INSTALLATION_ID = "60cf7ccf-4297-41f4-b76b-c0bd44dbe3d1"
REGISTRATION_VALUE = "".join(["A"] * 43)
DEVICE_TOKEN = "".join(["ab"] * 32)


class MobileNotificationErasureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.compliance_db = self.root / "compliance.sqlite3"
        self.old_private = os.environ.get("CYBERCHECK_PRIVATE_DIR")
        os.environ["CYBERCHECK_PRIVATE_DIR"] = str(self.root / "private")
        self.analytics_patch = mock.patch.object(analytics, "DB", self.root / "analytics.sqlite3")
        self.analytics_patch.start()
        self.old_mobile_dir, self.old_mobile_db = mobile_devices.DATA_DIR, mobile_devices.DB
        mobile_devices.DATA_DIR = self.root / "mobile"
        mobile_devices.DB = mobile_devices.DATA_DIR / "mobile.sqlite3"
        mobile_devices.init_db()
        mobile_devices.register({
            "installationId": INSTALLATION_ID,
            "registrationSecret": REGISTRATION_VALUE,
            "deviceToken": DEVICE_TOKEN,
            "environment": "sandbox",
        })
        self.old_notification_dir, self.old_notification_db = notification_broker.DATA_DIR, notification_broker.DB
        notification_broker.DATA_DIR = self.root / "notification"
        notification_broker.DB = notification_broker.DATA_DIR / "notification-broker.sqlite3"
        notification_privacy.init_db()
        self.request = compliance_store.create_rights_request(
            {"type": "erasure", "subjectRef": INSTALLATION_ID}, self.compliance_db
        )

    def tearDown(self):
        notification_broker.DATA_DIR, notification_broker.DB = self.old_notification_dir, self.old_notification_db
        mobile_devices.DATA_DIR, mobile_devices.DB = self.old_mobile_dir, self.old_mobile_db
        self.analytics_patch.stop()
        if self.old_private is None:
            os.environ.pop("CYBERCHECK_PRIVATE_DIR", None)
        else:
            os.environ["CYBERCHECK_PRIVATE_DIR"] = self.old_private
        self.tmp.cleanup()

    def _payload(self):
        return {"id": self.request["id"], "subjectRef": INSTALLATION_ID, "adapter": "mobile_installation"}

    def _bind(self) -> tuple[str, str]:
        subject_hash = privacy_suppression.identity_hash("installation", INSTALLATION_ID)
        recipient_key = f"sandbox:{DEVICE_TOKEN}"
        notification_privacy.bind_marketing_recipient(subject_hash, "push", recipient_key)
        return subject_hash, hashlib.sha256(recipient_key.encode("utf-8")).hexdigest()

    def _insert_delivery(self, key: str, recipient_hash: str, status: str, *, failure_class: str = "") -> None:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        with notification_broker.connect() as db:
            db.execute(
                """INSERT INTO notification_delivery(
                     idempotency_key,channel,category,reference,recipient_hash,status,
                     attempts,created_at,last_attempt_at,sent_at,last_error,failure_class
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (key, "push", "marketing_push", f"campaign-{key}", recipient_hash, status, 1,
                 now, now, now if status == "sent" else "", "transient" if failure_class else "", failure_class),
            )

    def test_erasure_suppresses_retryable_delivery_and_unlinks_privacy_binding(self):
        subject_hash, recipient_hash = self._bind()
        self._insert_delivery("failed-marketing", recipient_hash, "failed", failure_class="transient")
        self._insert_delivery("sent-marketing", recipient_hash, "sent")
        result = rights_execution_dispatch.execute(self._payload(), self.compliance_db)
        self.assertEqual(result["notificationPrivacy"], {
            "retryableDeliveriesSuppressed": 1,
            "retainedSentDeliveries": 1,
            "privacyBindingsRemoved": 1,
            "remainingPrivacyBindings": 0,
        })
        self.assertEqual(mobile_devices.status()["total"], 0)
        with notification_broker.connect() as db:
            binding_count = db.execute(
                "SELECT COUNT(*) n FROM notification_privacy_binding WHERE subject_hash=? AND channel='push'",
                (subject_hash,),
            ).fetchone()["n"]
            failed = db.execute("SELECT * FROM notification_delivery WHERE idempotency_key='failed-marketing'").fetchone()
            sent = db.execute("SELECT * FROM notification_delivery WHERE idempotency_key='sent-marketing'").fetchone()
        self.assertEqual(binding_count, 0)
        self.assertEqual(failed["failure_class"], "permanent")
        self.assertEqual(failed["permanent_state"], "resolved")
        self.assertEqual(failed["permanent_resolution"], "privacy_suppressed")
        self.assertEqual(sent["status"], "sent")
        self.assertNotIn(DEVICE_TOKEN, repr(result))
        self.assertNotIn(REGISTRATION_VALUE, repr(result))
        self.assertEqual(data_subject_rights.audit_rows(self.compliance_db)[0]["action"], "erase")

    def test_active_delivery_lease_defers_erasure_without_removing_mobile_data(self):
        subject_hash, recipient_hash = self._bind()
        self._insert_delivery("in-flight-marketing", recipient_hash, "delivering")
        with self.assertRaisesRegex(RuntimeError, "livraison en cours"):
            rights_execution_dispatch.execute(self._payload(), self.compliance_db)
        self.assertEqual(mobile_devices.status()["total"], 1)
        with notification_broker.connect() as db:
            binding_count = db.execute(
                "SELECT COUNT(*) n FROM notification_privacy_binding WHERE subject_hash=? AND channel='push'",
                (subject_hash,),
            ).fetchone()["n"]
        self.assertEqual(binding_count, 1)
        self.assertEqual(data_subject_rights.audit_rows(self.compliance_db), [])


if __name__ == "__main__":
    unittest.main()
