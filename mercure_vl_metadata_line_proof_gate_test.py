import unittest
from unittest.mock import patch,Mock
import mercure_vl_provider_metadata_resolver as resolver

class Tests(unittest.TestCase):
    def test_line_without_availability_is_rejected(self):
        observed={"centre_type":["1"],"utilisateur":["464"]}
        catalog={"1763":{"duration":"40","label":"TOUT VEHICULE HORS CAMPING CAR"}}
        with patch.object(resolver.mercure_vl_live_metadata_options,"fetch",return_value=observed),patch.object(
            resolver.mercure,"_session",return_value=Mock()),patch.object(
            resolver.mercure,"_check_auth",return_value=Mock(text="catalog")),patch.object(
            resolver.mercure_vl_embedded_service_catalog,"extract",return_value=catalog):
            with self.assertRaisesRegex(resolver.MercureVlMetadataResolutionError,"slot_evidence_required"):
                resolver.resolve(service="technical",line_id="454",operator_id="464",
                                 line_evidence={"observed":True,"lineId":"454","slotAvailable":False})
