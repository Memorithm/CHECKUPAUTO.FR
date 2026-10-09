import unittest
from mercure_vl_retry_policy import decide

class Tests(unittest.TestCase):
    def test_first_write_only_from_prepared(self):
        self.assertEqual(decide(state="prepared"),"write_once")

    def test_uncertain_effect_never_rewrites(self):
        self.assertEqual(decide(state="reconciliation_required"),"read_only_reconcile")
        self.assertEqual(decide(state="reconciliation_required",provider_reference="ref"),"read_only_reconcile")

    def test_confirmed(self):
        self.assertEqual(decide(state="confirmed",provider_reference="ref"),"return_confirmed")
