import tempfile
import unittest
from pathlib import Path
from unittest import mock

import compliance_store
import withdrawal_service as withdrawal


class WithdrawalServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "compliance.sqlite3"
        compliance_store.init_db(self.db)
        compliance_store.save_document({
            "type": "terms",
            "version": "2026-09",
            "title": "CGV",
            "body": "Conditions contractuelles de qualification. " * 8,
            "action": "publish",
        }, self.db)
        compliance_store.record_acceptance("rdv-123", db_path=self.db)

    def payload(self, **overrides):
        value = {
            "firstName": "Alice",
            "lastName": "Martin",
            "contractRef": "rdv-123",
            "receiptEmail": "alice@example.test",
            "confirm": True,
        }
        value.update(overrides)
        return value

    def test_submit_records_evidence_and_clears_email_after_receipt_delivery(self):
        with mock.patch.object(
            withdrawal.notifications,
            "send_email",
            return_value={"status": "sent", "sentAt": "2026-09-21T19:30:00+00:00"},
        ) as send:
            result = withdrawal.submit(self.payload(), self.db)

        self.assertTrue(result["contractMatched"])
        self.assertEqual(result["receiptStatus"], "sent")
        self.assertFalse(result["manualReviewRequired"])
        args, kwargs = send.call_args
        self.assertEqual(args[0], "alice@example.test")
        self.assertIn("rdv-123", args[2])
        self.assertIn(result["id"], args[2])
        self.assertEqual(kwargs["category"], "withdrawal_receipt")

        with compliance_store.connect(self.db) as db:
            row = db.execute(
                "SELECT receipt_email,receipt_email_hash,declaration_hash FROM withdrawal_requests"
            ).fetchone()
        self.assertEqual(row["receipt_email"], "")
        self.assertEqual(len(row["receipt_email_hash"]), 64)
        self.assertEqual(len(row["declaration_hash"]), 64)

    def test_unknown_contract_is_still_recorded_for_manual_matching(self):
        with mock.patch.object(
            withdrawal.notifications,
            "send_email",
            return_value={"status": "sent", "sentAt": "2026-09-21T19:30:00+00:00"},
        ):
            result = withdrawal.submit(
                self.payload(contractRef="customer-reference-not-yet-matched"),
                self.db,
            )
        self.assertFalse(result["contractMatched"])
        self.assertTrue(result["manualReviewRequired"])

    def test_transport_failure_never_discards_withdrawal_and_remains_retryable(self):
        with mock.patch.object(
            withdrawal.notifications,
            "send_email",
            side_effect=RuntimeError("provider private detail"),
        ), mock.patch.object(
            withdrawal.notifications,
            "safe_delivery_error",
            return_value="RuntimeError",
        ):
            result = withdrawal.submit(self.payload(), self.db)

        self.assertEqual(result["receiptStatus"], "failed")
        with compliance_store.connect(self.db) as db:
            row = db.execute(
                "SELECT receipt_email,receipt_status,receipt_last_error FROM withdrawal_requests"
            ).fetchone()
        self.assertEqual(row["receipt_email"], "alice@example.test")
        self.assertEqual(row["receipt_status"], "failed")
        self.assertEqual(row["receipt_last_error"], "RuntimeError")
        self.assertNotIn("private detail", row["receipt_last_error"])

    def test_pending_dispatch_retries_and_then_minimizes_recipient(self):
        with mock.patch.object(
            withdrawal.notifications,
            "send_email",
            return_value={"status": "deferred", "deferred": True, "retryAfterSeconds": 60},
        ):
            first = withdrawal.submit(self.payload(), self.db)
        self.assertEqual(first["receiptStatus"], "deferred")

        with mock.patch.object(
            withdrawal.notifications,
            "send_email",
            return_value={"status": "sent", "sentAt": "2026-09-21T19:35:00+00:00"},
        ):
            retry = withdrawal.dispatch_pending(self.db)
        self.assertEqual(retry["sent"], 1)
        with compliance_store.connect(self.db) as db:
            row = db.execute("SELECT receipt_email,receipt_status FROM withdrawal_requests").fetchone()
        self.assertEqual(row["receipt_email"], "")
        self.assertEqual(row["receipt_status"], "sent")

    def test_explicit_confirmation_is_required(self):
        with self.assertRaises(ValueError):
            withdrawal.submit(self.payload(confirm=False), self.db, dispatch=False)

    def test_public_page_has_required_direct_action_and_confirmation_wording(self):
        page = withdrawal.render_page(
            {
                "title": "Rétractation",
                "version": "1",
                "publishedAt": "2026-09-21",
                "body": "Informations sur le droit de rétractation.",
            },
            canonical_origin="https://www.checkupauto.fr",
        ).decode("utf-8")
        self.assertIn("Renoncer au contrat ici", page)
        self.assertIn("Confirmer la rétractation", page)
        self.assertIn('name="firstName"', page)
        self.assertIn('name="lastName"', page)
        self.assertIn('name="contractRef"', page)
        self.assertIn('name="receiptEmail"', page)
        self.assertIn('action="/retractation"', page)


if __name__ == "__main__":
    unittest.main()
