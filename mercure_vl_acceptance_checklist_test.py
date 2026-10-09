import unittest
from mercure_vl_acceptance_checklist import assess,REQUIRED

class Tests(unittest.TestCase):
    def test_empty_evidence_fails(self):
        self.assertFalse(assess({})["ready"])

    def test_payment_and_notifications_required(self):
        evidence={key:True for key in REQUIRED}
        evidence["payment_policy"]=False
        self.assertIn("payment_policy",assess(evidence)["missing"])

    def test_complete_evidence_does_not_deploy(self):
        result=assess({key:True for key in REQUIRED})
        self.assertTrue(result["ready"])
        self.assertFalse(result["deployed"])
