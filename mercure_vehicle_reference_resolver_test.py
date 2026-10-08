import unittest
from unittest.mock import patch

import mercure_vehicle_reference_resolver as resolver


class MercureVehicleReferenceResolverTest(unittest.TestCase):
    def setUp(self):
        self.refs={"marque":[{"id":"132","label":"Renault"}],
                   "energie":[{"id":"2","label":"Diesel"}]}
        self.models=[{"id":"1350","label":"Clio"}]

    def test_exact_case_insensitive_provider_mapping(self):
        with patch.object(resolver.lists,"fetch_references",return_value=self.refs), \
             patch.object(resolver.models_api,"models",return_value=self.models) as models:
            result=resolver.resolve(brand=" RENAULT ",model="clio",energy="diesel")
        self.assertEqual(result["brandId"],"132")
        self.assertEqual(result["modelId"],"1350")
        self.assertEqual(result["energyId"],"2")
        self.assertTrue(result["mappingVerified"])
        models.assert_called_once_with(centre_type="1",brand_id="132")

    def test_ambiguous_brand_is_rejected_before_model_read(self):
        refs={**self.refs,"marque":[{"id":"132","label":"Renault"},{"id":"200","label":"RENAULT"}]}
        with patch.object(resolver.lists,"fetch_references",return_value=refs), \
             patch.object(resolver.models_api,"models") as models:
            with self.assertRaisesRegex(resolver.VehicleReferenceResolutionError,"vehicle_reference_missing_or_ambiguous"):
                resolver.resolve(brand="Renault",model="Clio",energy="Diesel")
            models.assert_not_called()

    def test_generic_other_models_cannot_qualify_exact_vehicle(self):
        generic=[{"id":"1350","label":"AUTRES MODELES"}]
        with patch.object(resolver.lists,"fetch_references",return_value=self.refs), \
             patch.object(resolver.models_api,"models",return_value=generic):
            with self.assertRaisesRegex(resolver.VehicleReferenceResolutionError,
                                        "vehicle_reference_generic_model_unqualified"):
                resolver.resolve(brand="Renault",model="AUTRES MODELES",energy="Diesel")

    def test_unknown_model_is_rejected(self):
        with patch.object(resolver.lists,"fetch_references",return_value=self.refs), \
             patch.object(resolver.models_api,"models",return_value=self.models):
            with self.assertRaisesRegex(resolver.VehicleReferenceResolutionError,"vehicle_reference_missing_or_ambiguous"):
                resolver.resolve(brand="Renault",model="Unknown",energy="Diesel")


if __name__=="__main__":
    unittest.main()
