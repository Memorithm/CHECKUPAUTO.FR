import unittest
from mercure_step1_provider_metadata import qualify,FIELDS

class Tests(unittest.TestCase):
 def test_observed(self):
  values={key:"1" for key in FIELDS}
  self.assertEqual(qualify(values,{key:["1"] for key in FIELDS}),values)
 def test_missing_evidence(self):
  with self.assertRaises(ValueError):
   qualify({key:"1" for key in FIELDS},{})
 def test_pl_rejected(self):
  with self.assertRaises(ValueError):
   qualify({key:("2" if key=="centre_type" else "1") for key in FIELDS},{key:["1","2"] for key in FIELDS})
