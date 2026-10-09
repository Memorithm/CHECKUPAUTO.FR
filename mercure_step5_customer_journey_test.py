import unittest
from mercure_step5_customer_journey import evaluate,REQUIRED
class Tests(unittest.TestCase):
 def test_missing_confirmation(self):
  evidence={key:True for key in REQUIRED};evidence["confirmation_displayed"]=False
  self.assertEqual(evaluate(evidence)["missing"],["confirmation_displayed"])
 def test_no_false_claim_of_live_test(self):
  self.assertFalse(evaluate({key:True for key in REQUIRED})["liveTestPerformed"])
