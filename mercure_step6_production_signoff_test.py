import unittest
from mercure_step6_production_signoff import assess,REQUIRED
class Tests(unittest.TestCase):
 def test_default_not_approved(self):
  self.assertFalse(assess({})["approved"])
 def test_requires_payment_policy(self):
  evidence={key:True for key in REQUIRED};evidence["payment_policy_verified"]=False
  self.assertIn("payment_policy_verified",assess(evidence)["missing"])
 def test_no_activation_side_effect(self):
  self.assertFalse(assess({key:True for key in REQUIRED})["productionActivated"])
