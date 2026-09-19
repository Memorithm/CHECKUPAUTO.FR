import os
from pathlib import Path
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import app_download


class AppDownloadTest(unittest.TestCase):
    def setUp(self):
        self.config = {
            "seo": {"canonicalUrl": "https://checkupauto.fr/"}
        }

    def test_normalize_source_accepts_known_values_only(self):
        self.assertEqual(app_download.normalize_source("qr-centre"), "qr-centre")
        self.assertEqual(app_download.normalize_source("unexpected"), "direct")

    @patch.dict(os.environ, {app_download.APP_STORE_ENV: ""}, clear=False)
    def test_status_is_pending_without_app_store_url(self):
        status = app_download.status(self.config)
        self.assertFalse(status["ios"]["available"])
        self.assertIsNone(status["ios"]["appStoreUrl"])
        self.assertEqual(status["landingUrl"], "https://checkupauto.fr/app")
        page = app_download.landing_html(self.config, "<script>", "test-nonce").decode()
        self.assertIn('const source="direct";', page)
        self.assertIn('nonce="test-nonce"', page)
        self.assertIn("Bientôt sur l’App Store", page)

    @patch.dict(os.environ, {app_download.APP_STORE_ENV: "https://apps.apple.com/fr/app/checkup-auto/id1234567890"}, clear=False)
    def test_accepts_official_app_store_host(self):
        status = app_download.status(self.config)
        self.assertTrue(status["ios"]["available"])
        self.assertEqual(status["ios"]["appStoreUrl"], "https://apps.apple.com/fr/app/checkup-auto/id1234567890")

    @patch.dict(os.environ, {app_download.APP_STORE_ENV: "https://example.com/fake-app"}, clear=False)
    def test_rejects_external_redirect_host(self):
        self.assertEqual(app_download.ios_app_store_url(), "")

    def test_qr_and_poster_assets_are_valid_svg_xml(self):
        root = Path(__file__).resolve().parent / "assets" / "app"
        for name in ("qr-site.svg", "qr-centre.svg", "centre-poster.svg"):
            ET.parse(root / name)


if __name__ == "__main__":
    unittest.main()
