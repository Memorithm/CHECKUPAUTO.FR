import unittest
from mercure_vl_embedded_service_catalog import extract

class Tests(unittest.TestCase):
    def test_vl_only_catalog(self):
        html='''function prestationAndClientByCentreType(centreTypeId) {
        const prestations = [{"id":1763,"duree":40,"centre_type_id":1,
        "type_visite_libele_long":"CONTROLE TECHNIQUE"},
        {"id":9000,"duree":80,"centre_type_id":2}]; }'''
        result=extract(html)
        self.assertEqual(result["1763"]["duration"],"40")
        self.assertNotIn("9000",result)

    def test_missing_catalog_fails(self):
        with self.assertRaisesRegex(ValueError,"not_found"):
            extract("<html></html>")

    def test_duplicate_vl_service_fails(self):
        html='''function prestationAndClientByCentreType(x) {
        const prestations = [{"id":1763,"duree":40,"centre_type_id":1},
        {"id":1763,"duree":40,"centre_type_id":1}]; }'''
        with self.assertRaisesRegex(ValueError,"duplicate"):
            extract(html)
