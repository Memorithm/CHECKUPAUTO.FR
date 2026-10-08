"""Public cache must remain scoped, fingerprinted and privacy-preserving."""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parent


class PublicAssetCacheContractTest(unittest.TestCase):
    def test_model_digest_is_pinned_to_real_glb_file(self):
        expected = hashlib.sha256((ROOT / "assets/3d/CyberCheckVehicle_Photo3D.glb").read_bytes()).hexdigest()
        source = (ROOT / "assets/public-asset-cache.js").read_text()
        match = re.search(r'VEHICLE_GLB_SHA256\s*=\s*"([0-9a-f]{64})"', source)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), expected)
        self.assertIn('credentials: "omit"', source)
        self.assertIn('public_cache_digest_mismatch', source)
        self.assertIn('target.origin !== location.origin', source)
        self.assertIn('target.pathname !== VEHICLE_GLB_PATH', source)

    def test_litespeed_cache_is_scoped_to_public_3d_binary_media(self):
        path = ROOT / "assets/3d/.htaccess"
        self.assertTrue(path.is_file())
        content = path.read_text()
        self.assertIn('FilesMatch', content)
        self.assertIn('.glb', content)
        self.assertIn('max-age=604800', content)
        for forbidden in ('/api/', '/compte', 'CacheEnable public /', 'CacheEnable private /',
                          '/payment', '/contact', 'Set-Cookie', 'Authorization'):
            self.assertNotIn(forbidden, content)

    def test_hero_is_prioritized_and_below_the_fold_media_are_lazy(self):
        html = (ROOT / "index.html").read_text()
        self.assertRegex(html, r'class="vehicle-3d-fallback"[^>]*loading="eager" fetchpriority="high"')
        self.assertRegex(html, r'src="/assets/checkupauto-centre-map-osm.webp"[^>]*loading="lazy"')
        self.assertRegex(html, r'src="/assets/app/qr-site.svg"[^>]*loading="lazy"')
        self.assertIn('cache-model-20261008-1', html)
        loader = (ROOT / "assets/cybercheck-glb-hero.js").read_text()
        self.assertIn('getPublicVehicleGLB', loader)
        self.assertIn('afterFirstPaint', loader)
        self.assertIn('requestIdleCallback', loader)
        self.assertIn('navigator.connection?.saveData', loader)
        self.assertIn('GLISSEZ POUR EXPLORER', loader)

    def test_sensitive_responses_remain_uncached(self):
        server = (ROOT / "admin_server.py").read_text()
        self.assertIn("def send_bytes(self,data,ctype,status=200,cache='no-store'", server)
        customer = (ROOT / "customer_http.py").read_text()
        self.assertIn('LOGOUT_ROUTE="/api/customer/logout"', customer)
        self.assertNotIn('public-asset-cache.js', customer)
        js = (ROOT / "assets/public-asset-cache.js").read_text()
        for forbidden in ('/api/customer/', '/api/booking/', '/payment/', '/compte', '/contact'):
            self.assertNotIn('fetch("' + forbidden, js)


if __name__ == "__main__":
    unittest.main()
