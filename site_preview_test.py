import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

import site_preview as preview


class Sources(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sources, self.links, self.scripts = [], [], []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        for field in ('src', 'poster', 'srcset'):
            if field in values:
                self.sources.append(values[field])
        if 'href' in values:
            self.links.append(values['href'])
        if tag == 'script':
            self.scripts.append(values)


class SitePreviewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parent
        cls.page = preview.build(cls.root, 'a' * 40).decode('utf-8')
        cls.parsed = Sources()
        cls.parsed.feed(cls.page)

    def test_preview_uses_embedded_source_media_only(self):
        self.assertGreaterEqual(len(self.parsed.sources), 1)
        self.assertTrue(all(src.startswith(('data:image/webp;base64,', 'data:video/mp4;base64,')) for src in self.parsed.sources))
        self.assertTrue(all(href.startswith('#') for href in self.parsed.links))
        self.assertNotIn('assets/app/qr-site.svg', self.page)
        self.assertNotIn('src="/app.js', self.page)
        self.assertNotIn('src="/consent.js', self.page)

    def test_preview_embeds_the_real_local_centre_map_with_attribution(self):
        self.assertIn('Carte OpenStreetMap montrant le centre Checkup Auto', self.page)
        self.assertIn('© OpenStreetMap contributors', self.page)
        self.assertIn('class="centre-map-pin"', self.page)
        self.assertNotIn('<span>78</span>', self.page)

    def test_no_network_or_real_transaction_code_is_executed(self):
        self.assertEqual(self.parsed.scripts, [{}])
        for forbidden in ('fetch(', 'XMLHttpRequest', 'sendBeacon', 'WebSocket(', 'localStorage', 'sessionStorage'):
            self.assertNotIn(forbidden, preview.PREVIEW_JS)
        self.assertIn("connect-src 'none'", preview.CSP)
        self.assertIn("form-action 'none'", preview.CSP)
        self.assertIn('noindex,nofollow,noarchive', self.page)
        self.assertIn('DÉMONSTRATION DU SITE', self.page)
        self.assertNotIn('Disponibilités Mercure en temps réel', self.page)
        self.assertIn('CRÉNEAU FICTIF', self.page)

    def test_source_sha_and_real_visual_design_are_preserved(self):
        self.assertIn('aaaaaaaaaaaa', self.page)
        for text in ('L’exigence', 'La sérénité', 'inkCarStage', 'referral_wallet'):
            if text == 'referral_wallet':
                self.assertNotIn(text, self.page)
            elif text == 'inkCarStage':
                self.assertIn('id="inkCarStage"', self.page)
            else:
                self.assertIn(text, self.page)
        self.assertLess(len(self.page.encode()), 3 * 1024 * 1024)



    def test_site_preview_renders_inline_ink_art_without_any_3d_dependency(self):
        self.assertIn('id="inkCar"', self.page)
        self.assertIn('ink-draw', self.page)
        self.assertIn('OPTION 01 · TRAIT D’ENCRE', self.page)
        self.assertNotIn('vehicle3DCanvas', self.page)
        self.assertNotIn('cybercheck-glb-hero.js', self.page)
        self.assertNotIn('CyberCheckVehicle_Photo3D.glb', self.page)
        self.assertNotIn('vehicle-peugeot208-premium.webp', self.page)

    def test_booking_preview_starts_with_control_type_then_slot(self):
        self.assertIn('id="controlTypeSelector"', self.page)
        self.assertIn('data-service="technical"', self.page)
        self.assertIn('data-service="fitted"', self.page)
        self.assertIn('TYPE DE CONTRÔLE', self.page)
        self.assertIn('CRÉNEAU DISPONIBLE', self.page)
        self.assertNotIn('id="vehicleCarouselPrev"', self.page)

    def test_ink_hero_requires_no_external_runtime_or_cdn(self):
        source = (self.root / "index.html").read_text()
        assert '<svg id="inkCar"' in source
        assert 'src="/assets/cybercheck-glb-hero.js' not in source
        assert '<canvas id="vehicle3DCanvas"' not in source
        assert 'requestAnimationFrame(' not in source
        css = (self.root / "style.css").read_text()
        self.assertIn('@keyframes ink-draw-stroke', css)
        self.assertIn('@media(prefers-reduced-motion:reduce)', css)

    def test_invalid_source_sha_is_refused(self):
        with self.assertRaises(ValueError):
            preview.build(self.root, 'main')

    def test_unknown_media_and_active_content_are_refused(self):
        for target in ('https://outside.example/image.webp', '/private/key', '/assets/../private/key'):
            with self.subTest(target=target), self.assertRaises(ValueError):
                preview.PreviewHTML(self.root, '', 'a' * 40).media(target)
        with self.assertRaises(ValueError):
            preview.PreviewHTML(self.root, '', 'a' * 40).feed('<iframe src="https://outside.example"></iframe>')

    def test_symlink_and_oversized_source_are_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'actual').write_bytes(b'1234')
            (root / 'link').symlink_to(root / 'actual')
            with self.assertRaises(ValueError):
                preview.public_bytes(root, 'link', 10)
            with self.assertRaises(ValueError):
                preview.public_bytes(root, 'actual', 3)


if __name__ == '__main__':
    unittest.main()
