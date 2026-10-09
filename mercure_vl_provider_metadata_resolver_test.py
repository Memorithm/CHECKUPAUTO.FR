import unittest
from unittest.mock import patch
import mercure_vl_provider_metadata_resolver as resolver

class Tests(unittest.TestCase):
    def setUp(self):
        self.observed=dict(prestation=["1763"],duree=["40"],centre_type=["1"],
                           ligne_id=["454"],utilisateur=["464"])

    def test_qualified_options(self):
        with patch.object(resolver.mercure_vl_live_metadata_options,"fetch",return_value=self.observed):
            result=resolver.resolve(service="technical",line_id="454",operator_id="464")
        self.assertEqual(result["metadata"]["service_id"],"1763")

    def test_unknown_operator_rejected(self):
        with patch.object(resolver.mercure_vl_live_metadata_options,"fetch",return_value=self.observed):
            with self.assertRaises(resolver.MercureVlMetadataResolutionError):
                resolver.resolve(service="technical",line_id="454",operator_id="999")
