"""Approved lavis artwork fidelity, finite motion and public-only source boundaries."""
from pathlib import Path
import hashlib
from html.parser import HTMLParser
import json
import re
import unittest

ROOT=Path(__file__).resolve().parent
MASTER_SHA='87dcf1d5fab5c07eb50d4cf7dcf3bc26854427ad8370ff7c459a9501aa2cf94f'

class Markup(HTMLParser):
    def __init__(self,text):
        super().__init__();self.elements={};self.feed(text)
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if attrs.get('id'):self.elements[attrs['id']]=(tag,attrs)

class LavisHeroOption2Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html=(ROOT/'index.html').read_text();cls.css=(ROOT/'style.css').read_text();cls.js=(ROOT/'app.js').read_text()
        cls.dom=Markup(cls.html)

    def test_exact_approved_artwork_is_pinned_not_a_vector_approximation(self):
        master=ROOT/'assets/illustrations/checkupauto-lavis-option2-1530.webp'
        self.assertEqual(hashlib.sha256(master.read_bytes()).hexdigest(),MASTER_SHA)
        self.assertEqual(master.stat().st_size,223820)
        self.assertNotIn('<svg id="inkCar"',self.html)
        self.assertNotIn('ink-draw-stroke',self.css)
        self.assertEqual(self.dom.elements['lavisArtwork'][0],'img')

    def test_responsive_assets_remain_small_verified_and_local(self):
        manifest=json.loads((ROOT/'assets/illustrations/lavis-option2-manifest.json').read_text())
        self.assertEqual(len(manifest),3)
        limits={765:90000,1020:140000,1530:240000}
        for width,budget in limits.items():
            name=f'checkupauto-lavis-option2-{width}.webp';p=ROOT/'assets/illustrations'/name
            self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),manifest[name]['sha256'])
            self.assertEqual(p.stat().st_size,manifest[name]['bytes'])
            self.assertLess(p.stat().st_size,budget)
            self.assertEqual(p.read_bytes()[:4],b'RIFF')
            self.assertEqual(p.read_bytes()[8:12],b'WEBP')
            self.assertNotIn(b'EXIF',p.read_bytes())

    def test_image_is_accessible_dimensioned_and_priority_loaded(self):
        image=self.dom.elements['lavisArtwork'][1]
        self.assertEqual(image['width'],'1530');self.assertEqual(image['height'],'811')
        self.assertEqual(image['loading'],'eager');self.assertEqual(image['fetchpriority'],'high')
        self.assertGreater(len(image['alt']),30)
        self.assertIn('765w',image['srcset']);self.assertIn('1020w',image['srcset']);self.assertIn('1530w',image['srcset'])
        self.assertIn('(max-width: 980px) 92vw',image['sizes'])
        self.assertTrue(image['src'].startswith('/assets/illustrations/'))
        self.assertNotIn('http',image['srcset'])

    def test_no_3d_canvas_renderer_video_or_personal_mockup_content(self):
        for forbidden in ('<canvas','vehicle3DCanvas','cybercheck-glb-hero.js','CyberCheckVehicle_Photo3D.glb','<video','@gmail.com','Bonjour, Check Up','TABLEAU DE BORD CLIENT','500 000','20 000 avis'):
            self.assertNotIn(forbidden,self.html)
        self.assertNotIn('requestAnimationFrame',self.js)
        self.assertNotIn('getContext(',self.js)

    def test_animation_is_finite_and_never_distorts_the_art(self):
        css=self.css[self.css.index('/* Option 2:'):]
        self.assertIn('@keyframes lavis-reveal',css)
        self.assertIn('animation:lavis-reveal 2.6s',css)
        self.assertNotIn('infinite',css);self.assertNotRegex(css,r'(?<![-\w])filter\s*:')
        self.assertIn('object-fit:contain',css)
        self.assertIn('@media(prefers-reduced-motion:reduce)',css)
        self.assertIn('#lavisReplay{display:none}',css)
        self.assertIn('.lavis-controls[hidden]{display:none}',css)
        self.assertIn("image.classList.remove('lavis-revealing')",self.js)
        self.assertIn("image.addEventListener('animationend'",self.js)

    def test_static_image_replay_and_image_load_failure_are_explicit(self):
        for key in ('lavisReplay','lavisStill'):
            tag,attrs=self.dom.elements[key];self.assertEqual(tag,'button');self.assertEqual(attrs['type'],'button')
            self.assertEqual(attrs['aria-controls'],'lavisArtwork')
        self.assertEqual(self.dom.elements['lavisStill'][1]['aria-pressed'],'false')
        self.assertIn("still?.addEventListener('click',stop)",self.js)
        self.assertIn('observer?.disconnect()',self.js)
        self.assertIn("image.addEventListener('error'",self.js)
        self.assertIn("image.addEventListener('load',ready,{once:true})",self.js)
        self.assertIn("preference.addEventListener?.('change'",self.js)
        self.assertNotIn('fetch(',self.js.split("const service=document.querySelector('#service')")[0])

    def test_no_js_image_stays_visible_and_controls_start_hidden(self):
        self.assertIn('aria-label="Présentation de l’illustration" hidden',self.html)
        self.assertIn('.lavis-art{display:block',self.css)
        self.assertIn('opacity:1;clip-path:inset(0)',self.css)
        self.assertNotIn('class="lavis-art lavis-revealing"',self.html)
        self.assertEqual(self.dom.elements['lavisStatus'][1]['role'],'status')

    def test_anchors_and_cache_versions_preserve_navigation(self):
        self.assertIn('id="lavisHero"',self.html);self.assertIn('id="inkCarStage"',self.html)
        self.assertIn('#lavisHero,#inkCarStage{scroll-margin-top:120px}',self.css)
        self.assertIn('#lavisHero,#inkCarStage{scroll-margin-top:165px}',self.css)
        self.assertIn('/style.css?v=lavis-option2-20261008-1',self.html)
        self.assertIn('/app.js?v=lavis-option2-20261008-1',self.html)
        self.assertIn('href="#reservation"',self.html)
        self.assertIn('id="bookingContinue"',self.html)

if __name__=='__main__':unittest.main()
