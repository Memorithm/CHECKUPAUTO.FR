"""Contract tests for lightweight and accessible animated promotional flames."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class AnimatedPromotionalFlameTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.css = (ROOT / "style.css").read_text(encoding="utf-8")
        cls.page = (ROOT / "index.html").read_text(encoding="utf-8")
        cls.app = (ROOT / "app.js").read_text(encoding="utf-8")

    def test_animated_flames_use_existing_offer_marker_only(self):
        self.assertIn(".slot-button.low-demand .slot-flame", self.css)
        self.assertIn("slot.lowDemandOffer", self.app)
        self.assertIn("flame.setAttribute('aria-hidden','true')", self.app)
        self.assertIn("booking-flame-sway 2.6s ease-in-out infinite", self.css)

    def test_animation_uses_transform_and_opacity_not_layout_or_lights(self):
        self.assertIn("@keyframes booking-flame-sway", self.css)
        self.assertIn("@keyframes booking-flame-glow", self.css)
        self.assertIn("rotate(4deg) scale(1.17,1.10)", self.css)
        self.assertIn("opacity:.88", self.css)
        self.assertIn("radial-gradient(", self.css)
        css_motion = self.css[self.css.index("/* GPU-friendly transform/opacity only"):self.css.index("@media(prefers-reduced-motion:reduce)", self.css.index("/* GPU-friendly transform/opacity only"))]
        for forbidden in ("box-shadow:", "filter:", "background-position:", "height:", "width:", "top:", "left:", "visibility:", "display:"):
            self.assertNotIn(forbidden, css_motion)
        self.assertNotIn("url(", css_motion)

    def test_reduced_motion_disables_both_effects(self):
        self.assertIn("@media(prefers-reduced-motion:no-preference)", self.css)
        reduced = self.css[self.css.index("@media(prefers-reduced-motion:reduce)", self.css.index("/* GPU-friendly transform/opacity only")):]
        self.assertRegex(reduced, r"\.slot-button\.low-demand \.slot-flame::before\s*\{animation:none;transform:none\}")
        self.assertNotIn("booking-flame-sway", reduced)
        self.assertNotIn("booking-flame-glow", reduced)

    def test_stylesheet_cache_version_is_bumped(self):
        self.assertIn('/style.css?v=lavis-static-20261008-1', self.page)
        self.assertNotIn('/style.css?v=low-demand-20261008-1', self.page)


if __name__ == "__main__":
    unittest.main()
