import unittest
from unittest.mock import patch
import customer_booking_status_api as api

class Tests(unittest.TestCase):
    def test_reconciliation_state_visible_but_not_confirmed(self):
        with patch.object(api.journal,"status",return_value={
            "state":"reconciliation_required","confirmed":False}):
            result=api.status(account_id="customer1",request_key="booking-key-0000000001")
        self.assertFalse(result["confirmed"])
        self.assertTrue(result["reconciliationRequired"])

    def test_confirmed_state_has_no_reconciliation_flag(self):
        with patch.object(api.journal,"status",return_value={
            "state":"confirmed","confirmed":True}):
            result=api.status(account_id="customer1",request_key="booking-key-0000000001")
        self.assertTrue(result["confirmed"])
        self.assertFalse(result["reconciliationRequired"])
