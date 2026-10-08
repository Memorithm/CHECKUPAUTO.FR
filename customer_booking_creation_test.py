import datetime as dt
import os
import tempfile
import unittest
from unittest.mock import patch

import customer_booking_creation as creation
import customer_booking_journal as journal
from mercure_booking_write_contract import BookingWriteRequest, BookingWriteReceipt


class FakeWriter:
    def __init__(self, receipt=None, error=None):
        self.calls=0
        self.receipt=receipt or BookingWriteReceipt(provider_reference="mercure-123",accepted=True)
        self.error=error

    def create_once(self, request):
        self.calls+=1
        if self.error:
            raise self.error
        return self.receipt


class BookingCreationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{"CYBERCHECK_DATA_DIR":self.temp.name})
        self.env.start()
        self.request=BookingWriteRequest(
            request_key="booking-creation-test-key-001",account_id="customer-1",
            vehicle_id="vehicle-1",service="technical",
            date=(dt.date.today()+dt.timedelta(days=1)).isoformat(),
            time="10:30",price_cents=8000)

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_unqualified_default_never_creates_intent(self):
        with self.assertRaisesRegex(creation.BookingCreationError,"booking_provider_unqualified"):
            creation.create_and_verify(request=self.request)
        self.assertFalse(journal.database_path().exists())

    def test_simulated_create_reread_and_confirmation(self):
        writer=FakeWriter()
        with patch.object(creation.reconciliation.evidence,"verify_appointment",return_value=True) as read:
            result=creation.create_and_verify(request=self.request,provider=writer)
            replay=creation.create_and_verify(request=self.request,provider=writer)
        self.assertTrue(result["confirmed"])
        self.assertTrue(replay["confirmed"])
        self.assertEqual(writer.calls,1)
        read.assert_called_once()

    def test_untyped_receipt_cannot_confirm(self):
        writer=FakeWriter(receipt={"accepted":True,"provider_reference":"mercure-123"})
        result=creation.create_and_verify(request=self.request,provider=writer)
        self.assertFalse(result["confirmed"])
        self.assertEqual(result["state"],"reconciliation_required")

    def test_provider_timeout_is_not_retried(self):
        writer=FakeWriter(error=TimeoutError())
        with self.assertRaisesRegex(creation.BookingCreationError,"booking_provider_write_uncertain"):
            creation.create_and_verify(request=self.request,provider=writer)
        result=creation.create_and_verify(request=self.request,provider=writer)
        self.assertEqual(result["state"],"reconciliation_required")
        self.assertFalse(result["confirmed"])
        self.assertEqual(writer.calls,1)

    def test_unverified_provider_receipt_remains_uncertain(self):
        writer=FakeWriter()
        with patch.object(creation.reconciliation.evidence,"verify_appointment",return_value=False):
            result=creation.create_and_verify(request=self.request,provider=writer)
        self.assertFalse(result["confirmed"])
        self.assertEqual(writer.calls,1)


if __name__=="__main__":
    unittest.main()
