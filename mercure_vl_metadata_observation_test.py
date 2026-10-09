import unittest
from mercure_vl_metadata_observation import assess,REQUIRED

class Tests(unittest.TestCase):
    def test_real_observed_shape_is_incomplete(self):
        observed={"centre_type":["1","4"],"ligne_id":[],
                  "utilisateur":["464"],"prestation":[],"duree":[]}
        result=assess(observed)
        self.assertFalse(result["qualified"])
        self.assertEqual(result["missingObservations"],["ligne_id","prestation","duree"])
        self.assertFalse(result["customerWriteEnabled"])

    def test_complete_observation_not_write_authorization(self):
        result=assess({key:["1"] for key in REQUIRED})
        self.assertTrue(result["qualified"])
        self.assertFalse(result["customerWriteEnabled"])

    def test_unverified_field_rejected(self):
        with self.assertRaises(ValueError):
            assess({key:["fake"] for key in REQUIRED})
