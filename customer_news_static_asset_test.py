"""Security regression for the account-news JavaScript asset policy."""
import unittest
from pathlib import Path

import security_guard as security


class CustomerCarouselStaticAssetTest(unittest.TestCase):
    def test_exact_news_carousel_script_is_public(self):
        self.assertTrue(security.static_allowed("/assets/customer-announcements.js", False))
        self.assertTrue((Path(__file__).parent / "assets/customer-announcements.js").is_file())

    def test_other_javascript_files_remain_forbidden(self):
        for path in (
            "/assets/random.js",
            "/assets/privileged.js",
            "/assets/customer-announcements.js.bak",
            "/assets/../customer-announcements.js",
            "/assets/%2e%2e/customer-announcements.js",
            "/assets//customer-announcements.js",
            "/assets/customer-announcements.js/anything",
        ):
            with self.subTest(path=path):
                self.assertFalse(security.static_allowed(path, False))

    def test_admin_javascript_stays_restricted(self):
        self.assertFalse(security.static_allowed("/admin/index.js", False))


if __name__ == "__main__":
    unittest.main()
