import unittest
from dataclasses import replace
from unittest.mock import patch
import customer_booking_creation as creation
import customer_booking_journal as journal
import customer_booking_creation_test as fixtures
from customer_booking_creation_test import FakeWriter
from mercure_booking_identity_evidence import VerifiedBookingIdentity,BookingIdentityEvidenceError

class DurableIdentityTests(unittest.TestCase):
    setUp=fixtures.BookingCreationTests.setUp
    tearDown=fixtures.BookingCreationTests.tearDown
    def test_read_failure_preserves_receipt_and_retries_only_read(self):
        writer=FakeWriter()
        with patch.object(writer,'read_identity',side_effect=TimeoutError):
            with self.assertRaisesRegex(creation.BookingCreationError,'booking_provider_identity_unavailable'):
                creation.create_and_verify(request=self.request,provider=writer)
        self.assertEqual(journal.pending_provider_reference(account_id=self.request.account_id,key=self.request.request_key),'mercure-123')
        self.assertFalse(journal.status(account_id=self.request.account_id,key=self.request.request_key)['confirmed'])
        with patch.object(creation.reconciliation.evidence,'verify_appointment',return_value=True):
            result=creation.create_and_verify(request=self.request,provider=writer)
        self.assertTrue(result['confirmed']);self.assertEqual(writer.calls,1)
    def test_matching_calendar_without_identity_cannot_confirm(self):
        writer=FakeWriter()
        with patch.object(writer,'read_identity',return_value=None),patch.object(creation.reconciliation.evidence,'verify_appointment') as calendar:
            with self.assertRaises(BookingIdentityEvidenceError):creation.create_and_verify(request=self.request,provider=writer)
            calendar.assert_not_called()
        self.assertFalse(journal.status(account_id=self.request.account_id,key=self.request.request_key)['confirmed'])
    def test_foreign_vehicle_cannot_confirm(self):
        writer=FakeWriter()
        proof=VerifiedBookingIdentity('mercure-123',self.request.account_id,'other','technical',True)
        with patch.object(writer,'read_identity',return_value=proof):
            with self.assertRaisesRegex(BookingIdentityEvidenceError,'booking_identity_mismatch'):creation.create_and_verify(request=self.request,provider=writer)
    def test_write_only_adapter_is_rejected_before_persistence(self):
        class WriteOnly:
            def create_once(self,request):raise AssertionError('must not write')
        with self.assertRaisesRegex(creation.BookingCreationError,'booking_provider_unqualified'):
            creation.create_and_verify(request=self.request,provider=WriteOnly())
        self.assertFalse(journal.database_path().exists())
    def test_changed_request_cannot_reuse_uncertain_receipt(self):
        writer=FakeWriter()
        with patch.object(writer,'read_identity',side_effect=TimeoutError):
            with self.assertRaises(creation.BookingCreationError):creation.create_and_verify(request=self.request,provider=writer)
        with self.assertRaisesRegex(journal.BookingJournalError,'booking_idempotency_conflict'):
            creation.create_and_verify(request=replace(self.request,vehicle_id='other'),provider=writer)
        self.assertEqual(writer.calls,1)
    def test_reference_cannot_be_rebound_or_claimed_by_another_intent(self):
        key=self.request.request_key;aid=self.request.account_id
        journal.prepare(account_id=aid,key=key,request={});journal.require_reconciliation(account_id=aid,key=key)
        journal.record_provider_receipt(account_id=aid,key=key,provider_reference='ref-1')
        with self.assertRaisesRegex(journal.BookingJournalError,'booking_provider_reference_conflict'):
            journal.record_provider_receipt(account_id=aid,key=key,provider_reference='ref-2')
        journal.prepare(account_id=aid,key=key+'2',request={});journal.require_reconciliation(account_id=aid,key=key+'2')
        with self.assertRaisesRegex(journal.BookingJournalError,'booking_provider_reference_conflict'):
            journal.record_provider_receipt(account_id=aid,key=key+'2',provider_reference='ref-1')
