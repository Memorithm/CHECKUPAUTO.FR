import unittest
from mercure_step4_duplicate_guard import next_action
class Tests(unittest.TestCase):
 def test_uncertain_never_rewrites(self):
  self.assertEqual(next_action("reconciliation_required"),"read_only")
  self.assertEqual(next_action("reconciliation_required",provider_reference="ref"),"read_only")
 def test_prepared_once(self):
  self.assertEqual(next_action("prepared"),"create_once")
 def test_invalid(self):
  with self.assertRaises(ValueError):next_action("unknown")
