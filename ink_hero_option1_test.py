"""Homepage ink animation: SVG/CSS-only and zero 3D resource requests.

These static contracts complement the isolated Chromium and WebKit checks.
"""
from __future__ import annotations

from pathlib import Path
import re
import unittest
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parent


class InkHeroOption1Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page=(ROOT/"index.html").read_text(encoding="utf-8")
        cls.css=(ROOT/"style.css").read_text(encoding="utf-8")
        cls.js=(ROOT/"app.js").read_text(encoding="utf-8")
        svg=re.search(r'<svg id="inkCar".*?</svg>', cls.page, flags=re.S)
        if svg is None:
            raise AssertionError("SVG ink artwork missing")
        cls.svg_source=svg.group()
        cls.svg=ElementTree.fromstring(cls.svg_source)

    def test_ink_svg_is_tiny_standalone_and_accessible(self):
        self.assertLess(len(self.svg_source.encode("utf-8")), 14000)
        self.assertEqual(self.svg.attrib["role"],"img")
        self.assertEqual(self.svg.attrib["aria-labelledby"],"inkCarTitle inkCarDescription")
        self.assertIn("0 0 980 520",self.svg.attrib["viewBox"])
        self.assertIn('<title id="inkCarTitle">',self.svg_source)
        self.assertIn('<desc id="inkCarDescription">',self.svg_source)
        self.assertGreaterEqual(self.svg_source.count('class="ink-draw'),30)
        self.assertGreaterEqual(self.svg_source.count('class="ink-wash'),3)

    def test_svg_has_no_external_images_scripts_or_remote_resources(self):
        self.assertNotIn("<script",self.svg_source)
        self.assertNotIn("<image",self.svg_source)
        self.assertNotIn("<foreignObject",self.svg_source)
        self.assertNotIn("http://",self.svg_source.replace('xmlns="http://www.w3.org/2000/svg"', ""))
        self.assertNotIn("https://",self.svg_source)
        self.assertNotIn("href=",self.svg_source)
        self.assertNotIn("url(https:",self.svg_source)

    def test_homepage_has_no_3d_renderer_or_model_network_request(self):
        self.assertNotIn('src="/assets/cybercheck-glb-hero.js',self.page)
        self.assertNotIn('src="/assets/cybercheck-hero-3d.js',self.page)
        self.assertNotIn('CyberCheckVehicle_Photo3D.glb',self.page)
        self.assertNotIn('vehicle-peugeot208-premium.webp',self.page)
        self.assertNotIn('<canvas',self.page)
        self.assertNotIn('vehicle3DStage',self.page)
        self.assertNotIn('vehicle3DCanvas',self.page)
        self.assertIn('href="#reservation"',self.page)
        self.assertIn('id="inkReplay" type="button"',self.page)

    def test_animation_is_finite_css_only_and_accessible_on_reduced_motion(self):
        ink_css=self.css[self.css.index("/* Concept 01 — encre de Chine."): ]
        self.assertIn("@keyframes ink-draw-stroke",ink_css)
        self.assertIn("@keyframes ink-wash-appear",ink_css)
        self.assertIn("@media(prefers-reduced-motion:reduce)",ink_css)
        self.assertIn("stroke-dashoffset:0;opacity:1;",ink_css)
        self.assertNotIn("infinite",ink_css)
        self.assertIn(".ink-replay{display:none}",ink_css)
        self.assertNotIn("requestAnimationFrame",ink_css)
        self.assertIn('#inkCarStage{scroll-margin-top:120px}',ink_css)
        self.assertIn('@media(max-width:1100px){#inkCarStage{scroll-margin-top:165px}}',ink_css)

    def test_replay_does_not_manage_frames_or_contact_server(self):
        self.assertIn("document.getElementById('inkReplay')",self.js)
        self.assertIn("new IntersectionObserver",self.js)
        self.assertIn("visibleInk.disconnect()",self.js)
        self.assertIn("inkArtwork.classList.remove('ink-animate')",self.js)
        self.assertIn("inkArtwork.classList.add('ink-animate')",self.js)
        intro=self.js.split("const service=document.querySelector('#service')",1)[0]
        self.assertNotIn("fetch(",intro)
        self.assertNotIn("requestAnimationFrame",intro)
        self.assertNotIn("setInterval",intro)
        self.assertNotIn("WebGL",intro)

    def test_svg_uses_normalized_per_path_progress(self):
        paths=self.svg.findall(".//{http://www.w3.org/2000/svg}path")
        draw=[p for p in paths if "ink-draw" in p.attrib.get("class","")]
        self.assertGreaterEqual(len(draw),30)
        self.assertTrue(all(p.attrib.get("pathLength")=="100" for p in draw))
        self.assertTrue(all("--ink-delay:" in p.attrib.get("style","") for p in draw))

    def test_css_and_script_versions_are_bumped_for_new_hero(self):
        self.assertIn("/style.css?v=ink-option1-20261008-2",self.page)
        self.assertIn("/app.js?v=ink-option1-20261008-1",self.page)
        self.assertNotIn('src="/assets/cybercheck-glb-hero.js',self.page)


if __name__=="__main__":
    unittest.main()
