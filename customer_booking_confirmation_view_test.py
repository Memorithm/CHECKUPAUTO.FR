import unittest
from unittest.mock import patch
import customer_booking_confirmation_view as view

class Tests(unittest.TestCase):
    def test_pending_is_not_confirmed(self):
        with patch.object(view,"status",return_value={"confirmed":False}):
            self.assertFalse(view.view(account_id="a",request_key="key")["confirmed"])

    def test_verified_is_confirmed(self):
        with patch.object(view,"status",return_value={"confirmed":True}):
            self.assertTrue(view.view(account_id="a",request_key="key")["confirmed"])
