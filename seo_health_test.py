import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

_PRIVATE = Path(tempfile.mkdtemp(prefix="cybercheck-seo-test-"))
(_PRIVATE / "admin-password").write_text("unit-test-password\n")
os.environ["CYBERCHECK_PRIVATE_DIR"] = str(_PRIVATE)
os.environ["CYBERCHECK_SECURITY_DIR"] = str(_PRIVATE / "security")

import admin_server


class SeoHealthTest(unittest.TestCase):
    def setUp(self):
        self.config = json.loads(Path("data/site-config.json").read_text())

    def _health(self, config=None):
        with mock.patch.object(admin_server.gsc, "credential_info", return_value={"configured": False}), \
             mock.patch.object(admin_server.booking, "stats", return_value={"recent": [], "confirmedBookings": 0}):
            return admin_server.build_seo_health(config or self.config)
    def test_preview_crawler_effects_are_informational_not_duplicate_warnings(self):
        report = self._health()
        by_key = {item["key"]: item for item in report["checks"]}
        self.assertEqual(by_key["indexing"]["status"], "warning")
        self.assertEqual(by_key["googlebot"]["status"], "info")
        self.assertEqual(by_key["oai-search"]["status"], "info")
        self.assertEqual(by_key["perplexity"]["status"], "info")
        self.assertEqual(report["totals"]["info"], 3)
        self.assertEqual(report["totals"]["warning"], 4)
        self.assertEqual(report["totals"]["fail"], 0)

    def test_indexable_site_reports_blocked_search_crawler_as_warning(self):
        config = copy.deepcopy(self.config)
        config["seo"]["indexingEnabled"] = True
        config["seo"]["crawlers"]["googlebot"] = False
        report = self._health(config)
        by_key = {item["key"]: item for item in report["checks"]}
        self.assertEqual(by_key["googlebot"]["status"], "warning")
        self.assertEqual(by_key["oai-search"]["status"], "pass")
        self.assertEqual(by_key["perplexity"]["status"], "pass")


    def test_sitemap_contains_public_pricing_page_but_not_unreleased_app(self):
        xml = admin_server.build_sitemap(self.config)
        self.assertIn('<loc>https://www.checkupauto.fr/</loc>', xml)
        self.assertIn('<loc>https://www.checkupauto.fr/zone-tarifs</loc>', xml)
        self.assertNotIn('<loc>https://www.checkupauto.fr/app</loc>', xml)
        self.assertEqual(len(admin_server.sitemap_entries(self.config)), 2)

    def test_sitemap_adds_app_only_after_app_store_release(self):
        with mock.patch.dict(os.environ, {'CYBERCHECK_IOS_APP_URL': 'https://apps.apple.com/fr/app/checkup-auto/id1234567890'}, clear=False):
            entries = admin_server.sitemap_entries(self.config)
            self.assertEqual([item['loc'] for item in entries], [
                'https://www.checkupauto.fr/',
                'https://www.checkupauto.fr/zone-tarifs',
                'https://www.checkupauto.fr/app',
            ])



if __name__ == "__main__":
    unittest.main()
