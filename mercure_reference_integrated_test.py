import unittest
from unittest.mock import Mock,patch
import mercure_brand_energy_reference as dropdowns
import mercure_vehicle_reference as models
from mercure_reference_integrity import validate

class IntegratedReferenceTests(unittest.TestCase):
    def page(self, options):
        return '<select id="marque">'+options+'</select><select id="energie"><option value="2">Essence</option></select>'

    def test_dropdowns_reject_duplicate_provider_identity(self):
        for options in (
            '<option value="1">A</option><option value="1">B</option>',
            '<option value="1">A</option><option value="2"> a </option>',
            '<option value="1">Ａ</option><option value="2">A</option>',
            '<option value="1">'+'A'*121+'</option>',
        ):
            with self.subTest(options=options),self.assertRaises(ValueError):
                dropdowns.parse_references(self.page(options))

    def test_model_reader_rejects_ambiguity_and_overlong_labels(self):
        for rows in (
            [{'id':1,'libele':'208'},{'id':1,'libele':'308'}],
            [{'id':1,'libele':'A'*121}],
        ):
            session=Mock();session.get.return_value.json.return_value=rows
            with self.subTest(rows=rows),patch.object(models.mercure,'_session',return_value=session),patch.object(models.mercure,'_check_auth',side_effect=lambda r:r):
                with self.assertRaisesRegex(models.MercureReferenceError,'mercure_reference_invalid'):
                    models.models(centre_type='1',brand_id='132')
                session.post.assert_not_called()

    def test_unrelated_select_content_is_not_returned(self):
        page=self.page('<option value="132">PEUGEOT</option>')+'<select id="client"><option value="99">PRIVATE CLIENT</option></select>'
        result=dropdowns.parse_references(page)
        self.assertEqual(result['marque'],[{'id':'132','label':'PEUGEOT'}])
        self.assertNotIn('PRIVATE',repr(result))

    def test_control_characters_are_not_silently_normalized(self):
        with self.assertRaises(ValueError):validate([{'id':'1','label':'A\x00B'}])

    def test_duplicate_labels_are_omitted_not_guessed_and_do_not_block_other_brands(self):
        page=self.page('<option value="1">A</option><option value="2"> a </option><option value="132">PEUGEOT</option>')
        result=dropdowns.parse_references(page)
        self.assertEqual(result['marque'],[{'id':'132','label':'PEUGEOT'}])
