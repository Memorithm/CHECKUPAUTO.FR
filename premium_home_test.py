"""Premium presentation retains approved art and the application's booking boundaries."""
from __future__ import annotations

import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parent


class Tags(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.tags = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


class PremiumHomepageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (ROOT / 'index.html').read_text()
        cls.css = (ROOT / 'style.css').read_text()
        cls.tags = Tags(cls.page).tags

    def test_premium_presentation_is_scoped_to_public_homepage(self):
        self.assertEqual([a['class'] for tag, a in self.tags if tag == 'body'], ['site-home premium-home'])
        for source in ('customer_http.py', 'contact_request.py', 'payment_payline_http.py'):
            self.assertNotIn('premium-home', (ROOT / source).read_text())
        self.assertIn('.premium-home .hero h1{font-family:var(--serif)', self.css)
        self.assertNotIn('@import', self.css)
        self.assertNotIn('@font-face', self.css)
        self.assertIn('.premium-home .final h2{color:#244a32;', self.css)
        self.assertIn('.premium-home .final>p{color:#5b7854;', self.css)

    def test_business_copy_and_real_navigation_are_preserved(self):
        self.assertEqual(sum(t == 'h1' for t, _ in self.tags), 1)
        self.assertIn('L’exigence du détail.', self.page)
        self.assertIn('La sérénité en plus.', self.page)
        self.assertIn('href="#reservation">Réserver mon contrôle →</a>', self.page)
        self.assertIn('href="#centre">Notre centre ↗</a>', self.page)
        self.assertIn('href="/compte"', self.page)
        self.assertIn('id="bookingContinue"', self.page)
        self.assertIn('id="bookingDays"', self.page)
        self.assertIn('id="bookingStartDate"', self.page)
        for unsupported in ('500 000', '20 000 avis', '4,8 / 5', 'Nos centres'):
            self.assertNotIn(unsupported, self.page)

    def test_presentation_labels_and_controls_are_removed_not_hidden(self):
        for label in ('OPTION 02', 'OPTION 01', 'Démonstration de', 'Rejouer', 'Image fixe'):
            self.assertNotIn(label, self.page)
        for _, attrs in self.tags:
            classes = set(attrs.get('class', '').split())
            self.assertFalse(classes & {'lavis-topline', 'lavis-caption', 'lavis-controls', 'offer-seal'})
            self.assertNotIn(attrs.get('id'), {'lavisReplay', 'lavisStill', 'lavisToggle', 'inkReplay'})

    def test_same_approved_art_is_served_in_all_sizes(self):
        manifest = json.loads((ROOT / 'assets/illustrations/lavis-option2-manifest.json').read_text())
        image = next(a for tag, a in self.tags if tag == 'img' and a.get('id') == 'lavisArtwork')
        self.assertEqual((image['width'], image['height']), ('1530', '811'))
        self.assertEqual(image['fetchpriority'], 'high')
        self.assertEqual(image['loading'], 'eager')
        for filename, expected in manifest.items():
            with self.subTest(filename=filename):
                raw = (ROOT / 'assets/illustrations' / filename).read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), expected['sha256'])
                self.assertEqual(len(raw), expected['bytes'])
                self.assertIn(filename, image['srcset'])
        self.assertIn('object-fit:contain', self.css)
        self.assertIn('.premium-home .lavis-art{', self.css)
        for tag, a in self.tags:
            self.assertNotIn(tag, ('canvas', 'video'))
            self.assertNotIn('.glb', a.get('src', ''))
        self.assertNotIn('cybercheck-glb-hero', self.page)

    def test_phone_layout_places_art_between_headline_and_copy(self):
        self.assertIn('class="hero-intro"', self.page)
        self.assertIn('class="hero-details"', self.page)
        self.assertIn('.premium-home .hero-copy{display:contents}', self.css)
        self.assertIn('.premium-home .hero-intro{grid-row:1;', self.css)
        self.assertIn('.premium-home .hero-visual.lavis-hero{grid-row:2;', self.css)
        self.assertIn('.premium-home .hero-details{grid-row:3;', self.css)

    def test_commercial_offer_is_preserved_below_hero_not_on_the_art(self):
        hero = self.page.index('<section class="hero">')
        art = self.page.index('id="lavisArtwork"')
        offer = self.page.index('<div class="offer-banner">')
        planner = self.page.index('<section id="reservation"')
        self.assertLess(hero, art)
        self.assertLess(art, offer)
        self.assertLess(offer, planner)
        self.assertEqual(self.page.count('<div class="offer-banner">'), 1)
        self.assertIn('CONTRE-VISITE OFFERTE', self.page)
        self.assertIn('c.offer.title', (ROOT / 'app.js').read_text())

    def test_stylesheet_version_changes_without_new_runtime_script(self):
        self.assertIn('/style.css?v=premium-lavis-20261008-1', self.page)
        scripts = [a.get('src') for tag, a in self.tags if tag == 'script']
        self.assertEqual(scripts, ['/consent.js', '/app.js?v=desktop-week-picker-20261015-1'])


if __name__ == '__main__':
    unittest.main()
