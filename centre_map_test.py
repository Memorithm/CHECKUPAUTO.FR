from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent


class CentreMapTest(unittest.TestCase):
    def test_generator_is_pinned_to_the_centre_and_attributed_tile_source(self):
        source = (ROOT / "scripts" / "generate-centre-map.py").read_text()
        self.assertIn("LATITUDE = 48.980120", source)
        self.assertIn("LONGITUDE = 1.890251", source)
        self.assertIn("https://tile.openstreetmap.org/", source)
        self.assertIn("contact@checkupauto.fr", source)
        self.assertIn("loads no third-party map resources", source)

    def test_public_map_is_local_and_directions_use_the_exact_coordinates(self):
        page = (ROOT / "index.html").read_text()
        self.assertIn('src="/assets/checkupauto-centre-map-osm.webp"', page)
        self.assertIn('loading="lazy" fetchpriority="low"', page)
        self.assertIn('destination=48.980120%2C1.890251', page)
        self.assertIn('mlat=48.980120&amp;mlon=1.890251', page)
        self.assertNotIn('class="map-card"', page)


if __name__ == "__main__":
    unittest.main()
