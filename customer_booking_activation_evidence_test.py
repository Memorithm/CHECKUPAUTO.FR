import unittest
from customer_booking_activation_evidence import assess,REQUIRED

class Tests(unittest.TestCase):
    def test_missing_evidence_blocks(self):
        result=assess({})
        self.assertFalse(result["eligible"])
        self.assertIn("authoritative_slot",result["missing"])

    def test_complete_evidence_does_not_activate(self):
        result=assess({key:True for key in REQUIRED})
        self.assertTrue(result["eligible"])
        self.assertFalse(result["activated"])

    def test_payment_evidence_required(self):
        data={key:True for key in REQUIRED}
        data["payment_policy_verified"]=False
        self.assertIn("payment_policy_verified",assess(data)["missing"])
