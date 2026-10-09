import unittest
from mercure_vl_dynamic_metadata_fields import classify,readiness

class Tests(unittest.TestCase):
    def test_expected_structure(self):
        html='<input type="number" id="ligne_id"><select id="prestation"></select><input type="number" id="duree">'
        result=classify(html)
        self.assertTrue(readiness(result)["structureObserved"])
        self.assertFalse(readiness(result)["valuesQualified"])

    def test_missing_field(self):
        result=readiness(classify('<input type="number" id="ligne_id">'))
        self.assertIn("prestation",result["missingOrAmbiguous"])

    def test_ambiguous_field(self):
        result=readiness(classify('<input type="number" id="ligne_id"><input type="text" id="ligne_id">'))
        self.assertFalse(result["structureObserved"])
