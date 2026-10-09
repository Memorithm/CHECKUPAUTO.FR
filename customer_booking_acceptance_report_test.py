import unittest
from customer_booking_acceptance_report import report
from mercure_vl_acceptance_checklist import REQUIRED

class Tests(unittest.TestCase):
    def test_missing_evidence_blocks_homologation(self):
        result=report({})
        self.assertFalse(result["homologated"])
        self.assertIn("provider_write",result["missingEvidence"])

    def test_complete_evidence_does_not_activate(self):
        result=report({key:True for key in REQUIRED})
        self.assertTrue(result["homologated"])
        self.assertFalse(result["productionActivated"])
        self.assertEqual(result["scope"],"VL")
