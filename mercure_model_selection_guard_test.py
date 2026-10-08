import unittest
from mercure_model_selection_guard import validate,MercureModelSelectionError

class Tests(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(validate(brand_id="132",loaded_brand_id="132",model_id="42",models=[{"id":"42","label":"208"}]),"42")
    def test_brand_changed(self):
        with self.assertRaisesRegex(MercureModelSelectionError,"stale_brand"):
            validate(brand_id="145",loaded_brand_id="132",model_id="42",models=[{"id":"42"}])
    def test_model_missing(self):
        with self.assertRaisesRegex(MercureModelSelectionError,"unverified"):
            validate(brand_id="132",loaded_brand_id="132",model_id="99",models=[{"id":"42"}])
if __name__=="__main__": unittest.main()
