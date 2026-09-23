import hashlib
import os
import tempfile
import unittest
from pathlib import Path

import compliance_store
import data_subject_rights as rights
import mobile_devices
import notification_broker
import notification_privacy
import privacy_suppression


class NotificationPrivacyBridgeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)

        self.old_private = os.environ.get("CYBERCHECK_PRIVATE_DIR")
        os.environ["CYBERCHECK_PRIVATE_DIR"] = str(root / "private")

        self.old_broker_data = notification_broker.DATA_DIR
        self.old_broker_db = notification_broker.DB
        notification_broker.DATA_DIR = root / "broker"
        notification_broker.DB = notification_broker.DATA_DIR / "notification-broker.sqlite3"

        self.old_mobile_data = mobile_devices.DATA_DIR
        self.old_mobile_db = mobile_devices.DB
        mobile_devices.DATA_DIR = root / "mobile"
        mobile_devices.DB = mobile_devices.DATA_DIR / "mobile-devices.sqlite3"

        self.addCleanup(self._restore)
        self.compliance_db = root / "compliance.sqlite3"
        compliance_store.init_db(self.compliance_db)
        notification_broker.init_db()

    def _restore(self):
        notification_broker.DATA_DIR = self.old_broker_data
        notification_broker.DB = self.old_broker_db
        mobile_devices.DATA_DIR = self.old_mobile_data
        mobile_devices.DB = self.old_mobile_db
        if self.old_private is None:
            os.environ.pop("CYBERCHECK_PRIVATE_DIR", None)
        else:
            os.environ["CYBERCHECK_PRIVATE_DIR"] = self.old_private

    def _request(self, request_type, subject_ref):
        return compliance_store.create_rights_request(
            {"type": request_type, "subjectRef": subject_ref},
            self.compliance_db,
        )

    def _delivery(
        self,
        channel,
        category,
        reference,
        recipient_key,
        *,
        status="failed",
        failure_class="transient",
    ):
        key = notification_broker._delivery_key(
            channel, category, reference, recipient_key
        )
        recipient_hash = hashlib.sha256(
            recipient_key.strip().lower().encode("utf-8")
        ).hexdigest()
        stamp = "2026-09-23T12:00:00+00:00"
        with notification_broker.connect() as db:
            db.execute(
                """INSERT INTO notification_delivery(
                     idempotency_key,channel,category,reference,recipient_hash,status,
                     attempts,created_at,last_attempt_at,sent_at,last_error,failure_class,
                     next_attempt_at,transport_key
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    key,
                    channel,
                    category,
                    reference,
                    recipient_hash,
                    status,
                    1,
                    stamp,
                    stamp,
                    stamp if status == "sent" else "",
                    "TransientFailure" if failure_class else "",
                    failure_class,
                    "",
                    f"{channel}:test",
                ),
            )
        return key

    def test_email_objection_terminalizes_only_retryable_marketing_and_records_receipt(self):
        email = "alice@example.test"
        marketing_key = self._delivery(
            "email", "marketing_email", "campaign-retry", email
        )
        sent_key = self._delivery(
            "email",
            "marketing_email",
            "campaign-sent",
            email,
            status="sent",
            failure_class="",
        )
        transactional_key = self._delivery(
            "email", "ct_reminder", "ct-appointment-1", email
        )
        request = self._request("objection", email)

        result = rights.execute(
            request["id"],
            email,
            adapter="privacy_suppression",
            purpose="direct_marketing_email",
            db_path=self.compliance_db,
        )

        self.assertTrue(result["identityResolutionComplete"])
        with notification_broker.connect() as db:
            marketing = db.execute(
                "SELECT * FROM notification_delivery WHERE idempotency_key=?",
                (marketing_key,),
            ).fetchone()
            sent = db.execute(
                "SELECT * FROM notification_delivery WHERE idempotency_key=?",
                (sent_key,),
            ).fetchone()
            transactional = db.execute(
                "SELECT * FROM notification_delivery WHERE idempotency_key=?",
                (transactional_key,),
            ).fetchone()

        self.assertEqual(marketing["status"], "failed")
        self.assertEqual(marketing["failure_class"], "permanent")
        self.assertEqual(marketing["permanent_state"], "resolved")
        self.assertEqual(marketing["permanent_resolution"], "privacy_suppressed")
        self.assertEqual(marketing["next_attempt_at"], "")
        self.assertEqual(sent["status"], "sent")
        self.assertEqual(transactional["failure_class"], "transient")
        self.assertEqual(transactional["permanent_resolution"], "")

        receipts = privacy_suppression.store_receipts(
            request["id"], self.compliance_db
        )
        broker_receipts = [
            row for row in receipts if row["store"] == "notification_broker"
        ]
        self.assertEqual(len(broker_receipts), 1)
        self.assertEqual(broker_receipts[0]["scope"], "email")
        self.assertEqual(
            broker_receipts[0]["operation"], "suppress_retryable_marketing"
        )
        self.assertEqual(broker_receipts[0]["affectedRows"], 1)
        self.assertEqual(broker_receipts[0]["remainingActiveRows"], 0)
        self.assertEqual(len(broker_receipts[0]["evidenceHash"]), 64)
        self.assertNotIn(email, repr(broker_receipts))
        self.assertNotIn(email.encode(), notification_broker.DB.read_bytes())

        with self.assertRaises(notification_broker.PermanentDeliverySuppressed):
            notification_broker.send_email(
                email,
                "Offre",
                "Retry interdit",
                category="marketing_email",
                reference="campaign-retry",
            )

    def test_notification_receipt_is_idempotent_and_keeps_original_affected_count(self):
        email = "alice@example.test"
        self._delivery("email", "marketing_email", "campaign-retry", email)
        request = self._request("objection", email)

        first = privacy_suppression.suppress(
            "email",
            email,
            ["direct_marketing_email"],
            request_id=request["id"],
            db_path=self.compliance_db,
        )
        second = privacy_suppression.suppress(
            "email",
            email,
            ["direct_marketing_email"],
            request_id=request["id"],
            db_path=self.compliance_db,
        )

        first_broker = [
            row for row in first["storeReceipts"] if row["store"] == "notification_broker"
        ]
        second_broker = [
            row for row in second["storeReceipts"] if row["store"] == "notification_broker"
        ]
        self.assertEqual(len(first_broker), 1)
        self.assertEqual(len(second_broker), 1)
        self.assertEqual(first_broker[0]["affectedRows"], 1)
        self.assertEqual(second_broker[0]["affectedRows"], 1)
        self.assertEqual(
            first_broker[0]["evidenceHash"], second_broker[0]["evidenceHash"]
        )

    def test_push_objection_uses_current_mobile_token_without_persisting_it_in_broker(self):
        installation = "4a8c91bf-58e0-4bd3-8b43-7fd77303d20f"
        secret = "A" * 32
        token = "ab" * 32
        mobile_devices.register_installation(
            {"installationId": installation, "registrationSecret": secret}
        )
        mobile_devices.register(
            {
                "installationId": installation,
                "registrationSecret": secret,
                "deviceToken": token,
                "environment": "sandbox",
            }
        )
        recipient_key = f"sandbox:{token}"
        delivery_key = self._delivery(
            "push", "marketing_push", "push-campaign-retry", recipient_key
        )
        request = self._request("objection", installation)

        result = rights.execute(
            request["id"],
            installation,
            adapter="privacy_suppression",
            purpose="direct_marketing_push",
            db_path=self.compliance_db,
        )

        self.assertTrue(result["identityResolutionComplete"])
        with notification_broker.connect() as db:
            row = db.execute(
                "SELECT * FROM notification_delivery WHERE idempotency_key=?",
                (delivery_key,),
            ).fetchone()
        self.assertEqual(row["failure_class"], "permanent")
        self.assertEqual(row["permanent_resolution"], "privacy_suppressed")
        receipts = privacy_suppression.store_receipts(
            request["id"], self.compliance_db
        )
        broker_receipts = [
            item
            for item in receipts
            if item["store"] == "notification_broker" and item["scope"] == "push"
        ]
        self.assertEqual(len(broker_receipts), 1)
        self.assertEqual(broker_receipts[0]["affectedRows"], 1)
        broker_bytes = notification_broker.DB.read_bytes()
        self.assertNotIn(token.encode(), broker_bytes)
        self.assertNotIn(installation.encode(), broker_bytes)

    def test_binding_table_contains_only_pseudonymous_keys(self):
        email = "bind-me@example.test"
        subject_hash = privacy_suppression.identity_hash("email", email)
        result = notification_privacy.bind_marketing_recipient(
            subject_hash, "email", email
        )

        self.assertTrue(result["ok"])
        with notification_broker.connect() as db:
            row = db.execute(
                "SELECT subject_hash,channel,recipient_hash FROM notification_privacy_binding"
            ).fetchone()
        self.assertEqual(row["subject_hash"], subject_hash)
        self.assertEqual(row["channel"], "email")
        self.assertEqual(len(row["recipient_hash"]), 64)
        self.assertNotIn(email.encode(), notification_broker.DB.read_bytes())


if __name__ == "__main__":
    unittest.main()
