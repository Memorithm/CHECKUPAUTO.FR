import unittest
from unittest.mock import patch

import mercure_brand_energy_reference as ref


class MercureBrandEnergyReferenceTests(unittest.TestCase):
    def test_select_references_only(self):
        html='''<select id="marque"><option value="">Choose</option>
        <option value="132">Brand A</option></select>
        <select id="energie"><option value="2">Diesel</option></select>
        <select id="other"><option value="99">Private</option></select>'''
        result=ref.parse_references(html)
        self.assertEqual(result["marque"],[{"id":"132","label":"Brand A"}])
        self.assertEqual(result["energie"],[{"id":"2","label":"Diesel"}])
        self.assertNotIn("Private",str(result))

    def test_missing_dropdown_fails_closed(self):
        with self.assertRaisesRegex(ValueError,"mercure_reference_dropdown_missing"):
            ref.parse_references('<select id="marque"><option value="132">A</option></select>')

    def test_authenticated_calendar_page_is_read_only(self):
        session=unittest.mock.Mock()
        response=unittest.mock.Mock()
        response.text='<select id="marque"><option value="132">A</option></select><select id="energie"><option value="2">B</option></select>'
        session.get.return_value=response
        with patch.object(ref.mercure,"_session",return_value=session), \
             patch.object(ref.mercure,"_check_auth",side_effect=lambda x:x):
            result=ref.fetch_references()
        self.assertEqual(result["marque"][0]["id"],"132")
        session.post.assert_not_called()


if __name__=="__main__":
    unittest.main()
