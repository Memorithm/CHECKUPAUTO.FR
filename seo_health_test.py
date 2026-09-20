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


if __name__ == "__main__":
    unittest.main()
