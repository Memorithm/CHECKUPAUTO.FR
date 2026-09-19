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
        self.assertEqual(app_download.normalize_source("claim"), "claim")
        self.assertEqual(app_download.normalize_source("unexpected"), "direct")

    @patch.dict(os.environ, {
        app_download.APP_STORE_ENV: "",
        app_download.TESTFLIGHT_ENV: "",
    }, clear=False)
    def test_status_is_pending_without_distribution_url(self):
        status = app_download.status(self.config)
        self.assertFalse(status["ios"]["available"])
        self.assertEqual(status["ios"]["channel"], "pending")
        self.assertIsNone(status["ios"]["appStoreUrl"])
        self.assertIsNone(status["ios"]["testFlightUrl"])
        self.assertIsNone(status["ios"]["targetUrl"])
        self.assertEqual(status["landingUrl"], "https://checkupauto.fr/app")
        page = app_download.landing_html(self.config, "<script>", "test-nonce").decode()
        self.assertIn('const source="direct";', page)
        self.assertIn('nonce="test-nonce"', page)
        self.assertIn("Bientôt disponible sur iPhone", page)
        self.assertIn('name="robots" content="noindex,follow"', page)

    @patch.dict(os.environ, {
        app_download.APP_STORE_ENV: "https://apps.apple.com/fr/app/checkup-auto/id1234567890",
        app_download.TESTFLIGHT_ENV: "https://testflight.apple.com/join/AbC123xy",
    }, clear=False)
    def test_app_store_is_preferred_after_public_release(self):
        status = app_download.status(self.config)
        self.assertTrue(status["ios"]["available"])
        self.assertEqual(status["ios"]["channel"], "app-store")
        self.assertEqual(status["ios"]["targetUrl"], "https://apps.apple.com/fr/app/checkup-auto/id1234567890")
        self.assertEqual(status["ios"]["testFlightUrl"], "https://testflight.apple.com/join/AbC123xy")
        page = app_download.landing_html(self.config, "site", "test-nonce").decode()
        self.assertIn("Télécharger sur l’App Store", page)
        self.assertIn('name="robots" content="index,follow"', page)

    @patch.dict(os.environ, {
        app_download.APP_STORE_ENV: "",
        app_download.TESTFLIGHT_ENV: "https://testflight.apple.com/join/AbC123xy",
    }, clear=False)
    def test_testflight_public_link_enables_beta_distribution(self):
        status = app_download.status(self.config)
        self.assertTrue(status["ios"]["available"])
        self.assertEqual(status["ios"]["channel"], "testflight")
        self.assertEqual(status["ios"]["targetUrl"], "https://testflight.apple.com/join/AbC123xy")
        page = app_download.landing_html(self.config, "qr-centre", "test-nonce").decode()
        self.assertIn("Bêta iPhone disponible", page)
        self.assertIn("Tester avec TestFlight", page)
        self.assertIn('/go/app?src=qr-centre', page)
        self.assertIn('name="robots" content="noindex,follow"', page)

    @patch.dict(os.environ, {
        app_download.APP_STORE_ENV: "https://example.com/fake-app",
        app_download.TESTFLIGHT_ENV: "https://example.com/join/AbC123xy",
    }, clear=False)
    def test_rejects_external_redirect_hosts(self):
        self.assertEqual(app_download.ios_app_store_url(), "")
        self.assertEqual(app_download.ios_testflight_url(), "")

    @patch.dict(os.environ, {
        app_download.TESTFLIGHT_ENV: "https://testflight.apple.com/not-a-public-link",
    }, clear=False)
    def test_rejects_non_join_testflight_path(self):
        self.assertEqual(app_download.ios_testflight_url(), "")

    @patch.dict(os.environ, {
        app_download.TESTFLIGHT_ENV: "https://testflight.apple.com/join/AbC123xy?redirect=1",
    }, clear=False)
    def test_rejects_testflight_query_parameters(self):
        self.assertEqual(app_download.ios_testflight_url(), "")

    def test_qr_and_poster_assets_are_valid_svg_xml(self):
        root = Path(__file__).resolve().parent / "assets" / "app"
        for name in ("qr-site.svg", "qr-centre.svg", "centre-poster.svg"):
            ET.parse(root / name)


if __name__ == "__main__":
    unittest.main()
