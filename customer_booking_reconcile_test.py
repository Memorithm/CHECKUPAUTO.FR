import os
import tempfile
import unittest
from unittest.mock import patch

import customer_booking_journal as journal
import customer_booking_reconcile as reconcile


class BookingReconcileTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{"CYBERCHECK_DATA_DIR":self.temp.name})
        self.env.start()
        self.args={"account_id":"customer-1","request_key":"reconcile-key-test-00001",
                   "provider_reference":"mercure-123","date":"2026-10-15","time":"10:30"}
        journal.prepare(account_id="customer-1",key=self.args["request_key"],
                        request={"service":"technical","date":"2026-10-15","time":"10:30"})

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_prepared_request_never_queries_provider(self):
        with patch.object(reconcile.evidence,"verify_appointment") as provider:
            with self.assertRaisesRegex(reconcile.BookingReconciliationError,"booking_reconciliation_required"):
                reconcile.reconcile(**self.args)
            provider.assert_not_called()

    def test_missing_provider_evidence_never_confirms(self):
        journal.require_reconciliation(account_id="customer-1",key=self.args["request_key"])
        with patch.object(reconcile.evidence,"verify_appointment",return_value=False):
            result=reconcile.reconcile(**self.args)
        self.assertFalse(result["confirmed"])
        self.assertFalse(journal.status(account_id="customer-1",key=self.args["request_key"])["confirmed"])

    def test_independent_evidence_confirms_once(self):
        journal.require_reconciliation(account_id="customer-1",key=self.args["request_key"])
        with patch.object(reconcile.evidence,"verify_appointment",return_value=True) as provider:
            first=reconcile.reconcile(**self.args)
            second=reconcile.reconcile(**self.args)
        self.assertTrue(first["confirmed"])
        self.assertEqual(first,second)
        provider.assert_called_once()

    def test_other_customer_cannot_trigger_provider_read(self):
        journal.require_reconciliation(account_id="customer-1",key=self.args["request_key"])
        with patch.object(reconcile.evidence,"verify_appointment") as provider:
            with self.assertRaises(journal.BookingJournalError):
                reconcile.reconcile(**{**self.args,"account_id":"customer-2"})
            provider.assert_not_called()

    def test_provider_outage_does_not_advance_state(self):
        journal.require_reconciliation(account_id="customer-1",key=self.args["request_key"])
        with patch.object(reconcile.evidence,"verify_appointment",
                          side_effect=reconcile.evidence.MercureBookingEvidenceError("unavailable")):
            with self.assertRaisesRegex(reconcile.BookingReconciliationError,"booking_provider_evidence_unavailable"):
                reconcile.reconcile(**self.args)
        self.assertEqual(journal.status(account_id="customer-1",key=self.args["request_key"])["state"],
                         "reconciliation_required")


if __name__=="__main__":
    unittest.main()
