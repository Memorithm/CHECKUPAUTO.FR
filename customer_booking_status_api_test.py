import unittest
from unittest.mock import patch
import customer_booking_status_api as api

class Tests(unittest.TestCase):
    def test_confirmed_only_when_journal_explicit(self):
        with patch.object(api.journal,"status",return_value={"state":"confirmed","confirmed":True}):
            self.assertTrue(api.status(account_id="customer1",request_key="booking-key-0000000001")["confirmed"])

    def test_pending_is_not_confirmed(self):
        with patch.object(api.journal,"status",return_value={"state":"reconciliation_required","confirmed":False}):
            self.assertFalse(api.status(account_id="customer1",request_key="booking-key-0000000001")["confirmed"])

    def test_invalid_key_rejected_before_read(self):
        with patch.object(api.journal,"status") as reader:
            with self.assertRaises(api.BookingStatusError):
                api.status(account_id="customer1",request_key="short")
            reader.assert_not_called()
