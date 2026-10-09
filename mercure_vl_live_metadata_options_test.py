import unittest
from unittest.mock import Mock,patch
import mercure_vl_live_metadata_options as options

class Tests(unittest.TestCase):
    def test_extracts_exact_provider_option_values(self):
        html='<select id="ligne_id"><option value="454">Ligne</option></select>'
        self.assertEqual(options.extract(html)["ligne_id"],["454"])
        self.assertEqual(options.extract(html)["utilisateur"],[])

    def test_non_numeric_option_rejected(self):
        html='<select id="centre_type"><option value="pl">PL</option></select>'
        self.assertEqual(options.extract(html)["centre_type"],[])

    def test_authenticated_read_only(self):
        response=Mock(status_code=200,text='<select id="prestation"><option value="1763">CT</option></select>')
        session=Mock()
        session.get.return_value=response
        with patch.object(options.mercure,"_session",return_value=session),patch.object(
            options.mercure,"_check_auth",side_effect=lambda x:x):
            result=options.fetch()
        self.assertEqual(result["prestation"],["1763"])
        session.post.assert_not_called()
