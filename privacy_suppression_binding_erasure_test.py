import datetime
import hashlib
import os
import tempfile
import unittest
from pathlib import Path

import compliance_store
import data_subject_rights as rights
import notification_broker
import notification_privacy
import privacy_suppression


class PrivacySuppressionBindingErasureTest(unittest.TestCase):
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
        self.addCleanup(self._restore)
        self.compliance_db = root / "compliance.sqlite3"
        compliance_store.init_db(self.compliance_db)
        notification_broker.init_db()

    def _restore(self):
        notification_broker.DATA_DIR = self.old_broker_data
        notification_broker.DB = self.old_broker_db
        if self.old_private is None:
            os.environ.pop("CYBERCHECK_PRIVATE_DIR", None)
        else:
            os.environ["CYBERCHECK_PRIVATE_DIR"] = self.old_private

    def _request(self, request_type, subject_ref):
        return compliance_store.create_rights_request(
            {"type": request_type, "subjectRef": subject_ref},
            self.compliance_db,
        )

    def _delivery(self, email, reference, *, status="failed", failure_class="transient", last_attempt_at=None):
        recipient_hash = hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()
        key = notification_broker._delivery_key("email", "marketing_email", reference, email)
        stamp = last_attempt_at or "2026-09-23T12:00:00+00:00"
        with notification_broker.connect() as db:
            db.execute(
                """INSERT INTO notification_delivery(
                     idempotency_key,channel,category,reference,recipient_hash,status,
                     attempts,created_at,last_attempt_at,sent_at,last_error,failure_class,
                     next_attempt_at,transport_key
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    key,
                    "email",
                    "marketing_email",
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
                    "email:test",
                ),
            )
        return key

    def _binding_count(self, subject_hash):
        notification_privacy.init_db()
        with notification_broker.connect() as db:
            return int(
                db.execute(
                    """SELECT COUNT(*) n FROM notification_privacy_binding
                       WHERE subject_hash=? AND channel='email'""",
                    (subject_hash,),
                ).fetchone()["n"]
            )

    def test_erasure_unlinks_email_binding_after_terminalizing_retries_and_keeps_sent_evidence(self):
        email = "erase-binding@example.test"
        subject_hash = privacy_suppression.identity_hash("email", email)
        notification_privacy.bind_marketing_recipient(subject_hash, "email", email)
        retry_key = self._delivery(email, "campaign-retry")
        sent_key = self._delivery(email, "campaign-sent", status="sent", failure_class="")
        request = self._request("erasure", email)

        result = rights.execute(
            request["id"],
            email,
            adapter="privacy_suppression",
            db_path=self.compliance_db,
        )

        self.assertTrue(result["identityResolutionComplete"])
        self.assertEqual(self._binding_count(subject_hash), 0)
        with notification_broker.connect() as db:
            retry = db.execute(
                "SELECT * FROM notification_delivery WHERE idempotency_key=?", (retry_key,)
            ).fetchone()
            sent = db.execute(
                "SELECT * FROM notification_delivery WHERE idempotency_key=?", (sent_key,)
            ).fetchone()
        self.assertEqual(retry["failure_class"], "permanent")
        self.assertEqual(retry["permanent_resolution"], "privacy_suppressed")
        self.assertEqual(sent["status"], "sent")

        receipts = privacy_suppression.store_receipts(request["id"], self.compliance_db)
        binding_receipts = [row for row in receipts if row["store"] == "notification_privacy_binding"]
        self.assertEqual(len(binding_receipts), 1)
        self.assertEqual(binding_receipts[0]["scope"], "email")
        self.assertEqual(binding_receipts[0]["operation"], "erase_subject_binding")
        self.assertEqual(binding_receipts[0]["affectedRows"], 1)
        self.assertEqual(binding_receipts[0]["remainingActiveRows"], 0)
        self.assertEqual(len(binding_receipts[0]["evidenceHash"]), 64)
        self.assertNotIn(email, repr(receipts))
        self.assertNotIn(email.encode(), notification_broker.DB.read_bytes())
        self.assertIn(
            "notification_privacy_binding",
            privacy_suppression.summary(self.compliance_db)["storeEvidenceStores"],
        )

    def test_non_erasure_suppression_preserves_binding(self):
        email = "objection-binding@example.test"
        subject_hash = privacy_suppression.identity_hash("email", email)
        notification_privacy.bind_marketing_recipient(subject_hash, "email", email)
        self._delivery(email, "campaign-objection")
        request = self._request("objection", email)

        rights.execute(
            request["id"],
            email,
            adapter="privacy_suppression",
            purpose="direct_marketing_email",
            db_path=self.compliance_db,
        )

        self.assertEqual(self._binding_count(subject_hash), 1)
        receipts = privacy_suppression.store_receipts(request["id"], self.compliance_db)
        self.assertFalse(any(row["store"] == "notification_privacy_binding" for row in receipts))

    def test_active_delivery_lease_defers_erasure_then_retry_completes(self):
        email = "leased-binding@example.test"
        subject_hash = privacy_suppression.identity_hash("email", email)
        notification_privacy.bind_marketing_recipient(subject_hash, "email", email)
        recent = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        delivery_key = self._delivery(
            email,
            "campaign-in-flight",
            status="delivering",
            failure_class="transient",
            last_attempt_at=recent,
        )
        request = self._request("erasure", email)

        with self.assertRaisesRegex(RuntimeError, "livraison en cours"):
            rights.execute(
                request["id"],
                email,
                adapter="privacy_suppression",
                db_path=self.compliance_db,
            )
        self.assertEqual(self._binding_count(subject_hash), 1)
        self.assertEqual(privacy_suppression.store_receipts(request["id"], self.compliance_db), [])

        stale = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=10)).isoformat(timespec="seconds")
        with notification_broker.connect() as db:
            db.execute(
                "UPDATE notification_delivery SET last_attempt_at=? WHERE idempotency_key=?",
                (stale, delivery_key),
            )

        result = rights.execute(
            request["id"],
            email,
            adapter="privacy_suppression",
            db_path=self.compliance_db,
        )
        self.assertTrue(result["identityResolutionComplete"])
        self.assertEqual(self._binding_count(subject_hash), 0)
        receipts = privacy_suppression.store_receipts(request["id"], self.compliance_db)
        self.assertTrue(any(row["store"] == "notification_privacy_binding" for row in receipts))

    def test_binding_receipt_is_idempotent_after_physical_unlink(self):
        email = "replay-binding@example.test"
        subject_hash = privacy_suppression.identity_hash("email", email)
        notification_privacy.bind_marketing_recipient(subject_hash, "email", email)
        self._delivery(email, "campaign-replay")
        request = self._request("erasure", email)

        first = privacy_suppression.suppress(
            "email",
            email,
            ["all_processing"],
            request_id=request["id"],
            db_path=self.compliance_db,
        )
        second = privacy_suppression.suppress(
            "email",
            email,
            ["all_processing"],
            request_id=request["id"],
            db_path=self.compliance_db,
        )

        first_binding = [row for row in first["storeReceipts"] if row["store"] == "notification_privacy_binding"]
        second_binding = [row for row in second["storeReceipts"] if row["store"] == "notification_privacy_binding"]
        self.assertEqual(len(first_binding), 1)
        self.assertEqual(len(second_binding), 1)
        self.assertEqual(first_binding[0]["affectedRows"], 1)
        self.assertEqual(second_binding[0]["affectedRows"], 1)
        self.assertEqual(first_binding[0]["evidenceHash"], second_binding[0]["evidenceHash"])
        self.assertEqual(self._binding_count(subject_hash), 0)


if __name__ == "__main__":
    unittest.main()
