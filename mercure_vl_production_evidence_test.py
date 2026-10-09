import unittest
from mercure_vl_production_evidence import evaluate,REQUIRED

class Tests(unittest.TestCase):
    def test_missing_evidence(self):
        self.assertFalse(evaluate({})["eligible"])

    def test_payment_policy_required(self):
        evidence={key:True for key in REQUIRED}
        evidence["payment_policy_verified"]=False
        self.assertIn("payment_policy_verified",evaluate(evidence)["missing"])

    def test_eligible_does_not_activate_production(self):
        result=evaluate({key:True for key in REQUIRED})
        self.assertTrue(result["eligible"])
        self.assertFalse(result["productionActivated"])
        self.assertFalse(result["bookingConfirmed"])
