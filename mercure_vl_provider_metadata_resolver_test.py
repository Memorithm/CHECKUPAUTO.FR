import unittest
from unittest.mock import patch,Mock
import mercure_vl_provider_metadata_resolver as resolver

class Tests(unittest.TestCase):
    def setUp(self):
        self.observed={"centre_type":["1"],"utilisateur":["464"],
                       "ligne_id":[],"prestation":[],"duree":[]}
        self.catalog={"1763":{"duration":"40","label":"TOUT VEHICULE HORS CAMPING CAR"}}

    def test_matching_catalog_still_requires_line_proof(self):
        with patch.object(resolver.mercure_vl_live_metadata_options,"fetch",return_value=self.observed),patch.object(
            resolver.mercure,"_session",return_value=Mock()),patch.object(
            resolver.mercure,"_check_auth",return_value=Mock(text="catalog")),patch.object(
            resolver.mercure_vl_embedded_service_catalog,"extract",return_value=self.catalog):
            with self.assertRaisesRegex(resolver.MercureVlMetadataResolutionError,"line_evidence_required"):
                resolver.resolve(service="technical",line_id="454",operator_id="464")

    def test_wrong_catalog_duration_rejected(self):
        wrong={"1763":{"duration":"10","label":"TOUT VEHICULE HORS CAMPING CAR"}}
        with patch.object(resolver.mercure_vl_live_metadata_options,"fetch",return_value=self.observed),patch.object(
            resolver.mercure,"_session",return_value=Mock()),patch.object(
            resolver.mercure,"_check_auth",return_value=Mock(text="catalog")),patch.object(
            resolver.mercure_vl_embedded_service_catalog,"extract",return_value=wrong):
            with self.assertRaisesRegex(resolver.MercureVlMetadataResolutionError,"catalog_mismatch"):
                resolver.resolve(service="technical",line_id="454",operator_id="464")
