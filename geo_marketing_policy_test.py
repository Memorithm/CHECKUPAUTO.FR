import unittest
from unittest import mock

import geo_marketing as geo


SERVICES = [
    {"key": "technical", "label": "Contrôle technique", "basePrice": 80.0},
]
CATALOG = {
    "center": {"name": "Les Mureaux"},
    "count": 3,
    "communes": [
        {"name": "Proche", "postalCodes": ["78130"], "distanceKm": 5.0, "population": 1000},
        {"name": "Limite", "postalCodes": ["78000"], "distanceKm": 15.0, "population": 500},
        {"name": "Lointaine", "postalCodes": ["75000"], "distanceKm": 25.0, "population": 100000},
    ],
}


class GeoMarketingPolicyTest(unittest.TestCase):
    def test_priority_markets_never_promote_outside_configured_radius(self):
        config = {"geoAcquisition": {"enabled": True, "radiusKm": 15.0, "priorityMarketCount": 36}}
        with mock.patch.object(geo, "catalog", return_value=CATALOG):
            markets = geo.priority_markets(config, SERVICES)
        self.assertEqual([row["name"] for row in markets], ["Proche", "Limite"])
        self.assertTrue(all(row["distanceKm"] <= 15.0 for row in markets))

    def test_disabled_acquisition_has_no_priority_markets(self):
        config = {"geoAcquisition": {"enabled": False, "radiusKm": 50.01}}
        with mock.patch.object(geo, "catalog", return_value=CATALOG):
            self.assertEqual(geo.priority_markets(config, SERVICES), [])

    def test_coverage_count_matches_effective_policy_and_reports_catalog_size(self):
        config = {"geoAcquisition": {"enabled": True, "radiusKm": 15.0}}
        with mock.patch.object(geo, "catalog", return_value=CATALOG):
            result = geo.coverage(config, SERVICES)
        self.assertEqual(result["communeCount"], 2)
        self.assertEqual(result["catalogCommuneCount"], 3)
        self.assertEqual(len(result["markets"]), 2)

    def test_invalid_catalog_distance_is_excluded_from_acquisition(self):
        catalog = {
            **CATALOG,
            "count": 4,
            "communes": CATALOG["communes"] + [
                {"name": "Invalide", "postalCodes": [], "distanceKm": "unknown", "population": 999999}
            ],
        }
        with mock.patch.object(geo, "catalog", return_value=catalog):
            markets = geo.priority_markets({"geoAcquisition": {"radiusKm": 50.01}}, SERVICES)
        self.assertNotIn("Invalide", [row["name"] for row in markets])


if __name__ == "__main__":
    unittest.main()
