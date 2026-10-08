import os
import tempfile
import unittest
from unittest.mock import patch

import customer_booking_journal as journal
import customer_booking_reconcile as reconcile
from mercure_booking_identity_evidence import (
    BookingIdentityEvidenceError, VerifiedBookingIdentity,
)


class BookingIdentityGateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{"CYBERCHECK_DATA_DIR":self.temp.name})
        self.env.start()
        self.key="identity-gated-booking-key-0001"
        journal.prepare(account_id="customer-1",key=self.key,request={"service":"technical"})
        journal.require_reconciliation(account_id="customer-1",key=self.key)
        self.args=dict(account_id="customer-1",request_key=self.key,
                       provider_reference="mercure-123",date="2026-10-15",
                       time="10:30",vehicle_id="vehicle-1",service="technical")

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_no_identity_evidence_cannot_query_calendar(self):
        with patch.object(reconcile.evidence,"verify_appointment") as read:
            with self.assertRaisesRegex(BookingIdentityEvidenceError,"booking_identity_evidence_missing"):
                reconcile.reconcile_with_identity(**self.args,identity_evidence=None)
            read.assert_not_called()

    def test_foreign_vehicle_is_rejected(self):
        proof=VerifiedBookingIdentity("mercure-123","customer-1","vehicle-2","technical",True)
        with patch.object(reconcile.evidence,"verify_appointment") as read:
            with self.assertRaisesRegex(BookingIdentityEvidenceError,"booking_identity_mismatch"):
                reconcile.reconcile_with_identity(**self.args,identity_evidence=proof)
            read.assert_not_called()

    def test_verified_identity_and_calendar_are_both_required(self):
        proof=VerifiedBookingIdentity("mercure-123","customer-1","vehicle-1","technical",True)
        with patch.object(reconcile.evidence,"verify_appointment",return_value=False):
            result=reconcile.reconcile_with_identity(**self.args,identity_evidence=proof)
        self.assertFalse(result["confirmed"])
        with patch.object(reconcile.evidence,"verify_appointment",return_value=True):
            result=reconcile.reconcile_with_identity(**self.args,identity_evidence=proof)
        self.assertTrue(result["confirmed"])


if __name__=="__main__":
    unittest.main()
