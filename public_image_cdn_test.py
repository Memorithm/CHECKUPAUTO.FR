"""Cloudflare Pages images only; default off; preserve all dynamic requests."""
from __future__ import annotations

import os
from pathlib import Path
import unittest
from unittest.mock import patch

import public_image_cdn as cdn

ROOT = Path(__file__).resolve().parent


class PublicImageCDNTest(unittest.TestCase):
    def test_flag_off_preserves_homepage_byte_for_byte(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        with patch.dict(os.environ, {"CYBERCHECK_PUBLIC_IMAGE_CDN_ORIGIN": ""}):
            self.assertEqual(cdn.rewrite_homepage_images(html), html)

    def test_exact_host_rewrites_srcset_and_preload_images_only(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        out = cdn.rewrite_homepage_images(html, origin="https://static.checkupauto.fr")
        self.assertIn('src="https://static.checkupauto.fr/assets/illustrations/', out)
        self.assertIn('imagesrcset="https://static.checkupauto.fr/assets/illustrations/', out)
        self.assertIn(', https://static.checkupauto.fr/assets/illustrations/', out)
        self.assertIn('src="/consent.js"', out)
        self.assertIn('src="/app.js?v=', out)
        self.assertIn('href="/style.css?v=', out)
        self.assertIn('href="/compte"', out)
        self.assertIn('href="/contact"', out)
        self.assertNotIn("static.checkupauto.fr/api/", out)
        self.assertNotIn("static.checkupauto.fr/compte", out)
        self.assertNotIn("static.checkupauto.fr/auth", out)

    def test_unapproved_domain_and_unsafe_schemes_are_no_op(self):
        sample = '<img src="/assets/illustrations/hero.webp">'
        for origin in ("https://example.com", "http://static.checkupauto.fr",
                       "https://static.checkupauto.fr.evil.com",
                       "https://static.checkupauto.fr/path",
                       "https://static.checkupauto.fr?x=1"):
            with self.subTest(origin=origin):
                self.assertEqual(cdn.rewrite_homepage_images(sample, origin=origin), sample)

    def test_only_image_attributes_and_public_prefixes_are_eligible(self):
        sample = ('<img src="/assets/illustrations/hero.webp">'
                  '<img src="/assets/3d/secret.png">'
                  '<a href="/assets/illustrations/paper.webp">image</a>'
                  '<script src="/assets/app/code.js"></script>'
                  '<div data-url="/assets/illustrations/hero.webp"></div>'
                  '<a href="/api/customer/profile">Profil</a>')
        rewritten = cdn.rewrite_homepage_images(sample, origin="https://static.checkupauto.fr")
        self.assertEqual(rewritten.count("https://static.checkupauto.fr"), 2)
        self.assertIn('<img src="/assets/3d/secret.png">', rewritten)
        self.assertIn('src="/assets/app/code.js"', rewritten)
        self.assertIn('data-url="/assets/illustrations/hero.webp"', rewritten)
        self.assertIn('href="/api/customer/profile"', rewritten)

    def test_staging_uses_verified_pages_public_assets_without_custom_dns(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        with patch.dict(os.environ, {}, clear=True):
            out = cdn.rewrite_homepage_images(html, host="test.checkupauto.fr")
            self.assertIn('src="https://checkupauto-fr.pages.dev/assets/illustrations/', out)
            self.assertIn('imagesrcset="https://checkupauto-fr.pages.dev/assets/illustrations/', out)
            self.assertIn('href="/style.css?v=', out)
            self.assertIn('src="/app.js?v=', out)
            self.assertIn('href="/compte"', out)
            self.assertIn('href="/contact"', out)
            for host in ("checkupauto.fr", "www.checkupauto.fr", "test.checkupauto.fr.evil.com",
                         "test.checkupauto.fr:443", ""):
                with self.subTest(host=host):
                    self.assertEqual(cdn.rewrite_homepage_images(html, host=host), html)

    def test_staging_can_be_disabled_immediately_by_runtime_flag(self):
        sample = '<img src="/assets/illustrations/hero.webp">'
        with patch.dict(os.environ, {"CYBERCHECK_PUBLIC_IMAGE_CDN_ORIGIN": "off"}):
            self.assertEqual(cdn.rewrite_homepage_images(sample, host="test.checkupauto.fr"), sample)
        with patch.dict(os.environ, {"CYBERCHECK_PUBLIC_IMAGE_CDN_ORIGIN": ""}):
            self.assertEqual(cdn.rewrite_homepage_images(sample, host="test.checkupauto.fr"), sample)
        with patch.dict(os.environ, {"CYBERCHECK_PUBLIC_IMAGE_CDN_ORIGIN": "http://checkupauto-fr.pages.dev"}):
            self.assertEqual(cdn.rewrite_homepage_images(sample, host="test.checkupauto.fr"), sample)
        with patch.dict(os.environ, {"CYBERCHECK_PUBLIC_IMAGE_CDN_ORIGIN": "https://checkupauto-fr.pages.dev.evil.com"}):
            self.assertEqual(cdn.rewrite_homepage_images(sample, host="test.checkupauto.fr"), sample)

    def test_manual_approved_flag_is_still_supported_without_redirecting_clients(self):
        sample = ('<img src="/assets/illustrations/hero.webp">'
                  '<a href="/compte">Compte</a><script src="/app.js"></script>')
        with patch.dict(os.environ, {"CYBERCHECK_PUBLIC_IMAGE_CDN_ORIGIN": "https://static.checkupauto.fr"}):
            out = cdn.rewrite_homepage_images(sample, host="checkupauto.fr")
            self.assertIn('src="https://static.checkupauto.fr/assets/illustrations/hero.webp"', out)
            self.assertIn('href="/compte"', out)
            self.assertIn('src="/app.js"', out)

    def test_admin_render_index_source_keeps_default_no_cdn(self):
        src = (ROOT / "admin_server.py").read_text(encoding="utf-8")
        self.assertIn("public_image_cdn.rewrite_homepage_images(raw,host=", src)
        self.assertNotIn("https://static.checkupauto.fr", src)


if __name__ == "__main__":
    unittest.main()
