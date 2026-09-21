import unittest

import app_download


class AppDownloadCanonicalOriginTest(unittest.TestCase):
    def test_accepts_the_production_https_origin(self):
        config = {"seo": {"canonicalUrl": "https://www.checkupauto.fr/"}}
        self.assertEqual(
            app_download.canonical_origin(config),
            "https://www.checkupauto.fr",
        )

    def test_insecure_origin_fails_closed_to_production(self):
        config = {"seo": {"canonicalUrl": "http://www.checkupauto.fr/"}}
        status = app_download.status(config)
        self.assertEqual(status["landingUrl"], "https://www.checkupauto.fr/app")

    def test_foreign_origin_cannot_rewrite_app_distribution_links(self):
        config = {"seo": {"canonicalUrl": "https://example.invalid/"}}
        page = app_download.landing_html(config, "qr-centre", "nonce").decode()
        self.assertIn(
            '<link rel="canonical" href="https://www.checkupauto.fr/app">',
            page,
        )
        self.assertNotIn("example.invalid", page)

    def test_userinfo_and_nonstandard_port_fail_closed(self):
        for value in (
            "https://user@www.checkupauto.fr/",
            "https://www.checkupauto.fr:444/",
        ):
            with self.subTest(value=value):
                self.assertEqual(
                    app_download.canonical_origin({"seo": {"canonicalUrl": value}}),
                    "https://www.checkupauto.fr",
                )


if __name__ == "__main__":
    unittest.main()
