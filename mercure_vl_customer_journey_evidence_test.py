import unittest
from mercure_vl_customer_journey_evidence import evaluate,REQUIRED

class Tests(unittest.TestCase):
    def test_unverified_calendar_blocks_confirmation(self):
        evidence={key:True for key in REQUIRED}
        evidence["calendar_verified"]=False
        self.assertIn("calendar_verified",evaluate(evidence)["missing"])

    def test_customer_confirmation_is_required(self):
        evidence={key:True for key in REQUIRED}
        evidence["confirmation_visible"]=False
        self.assertFalse(evaluate(evidence)["passed"])

    def test_no_real_booking_claim(self):
        result=evaluate({key:True for key in REQUIRED})
        self.assertTrue(result["passed"])
        self.assertFalse(result["realBookingPerformed"])
