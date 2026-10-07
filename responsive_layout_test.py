from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent


class ResponsiveLayoutTest(unittest.TestCase):
    def test_public_page_uses_safe_area_viewport_and_cache_busted_css(self):
        page = (ROOT / "index.html").read_text()
        self.assertIn("width=device-width,initial-scale=1,viewport-fit=cover", page)
        self.assertIn("/style.css?v=responsive-4", page)

    def test_public_css_covers_phone_tablet_and_touch_layouts(self):
        css = (ROOT / "style.css").read_text()
        self.assertIn("Responsive adaptive layer v1", css)
        for breakpoint in ("@media(max-width:760px)", "@media(max-width:640px)", "@media(max-width:480px)", "@media(max-width:360px)"):
            self.assertIn(breakpoint, css)
        self.assertIn(".vehicle-option{flex:0 0 100%", css)
        self.assertIn(".booking-slots{grid-template-columns:1fr}", css)
        self.assertIn("Mobile interaction refinement v2", css)
        self.assertIn(".booking-days{display:flex;grid-template-columns:none", css)
        self.assertIn(".booking-day{flex:0 0 92%;scroll-snap-align:start", css)
        self.assertIn(".vehicle-carousel-arrow{min-width:44px;width:44px}", css)
        self.assertIn(".app-qr-card{grid-template-columns:1fr", css)
        self.assertIn("env(safe-area-inset-left)", css)

    def test_admin_keeps_navigation_accessible_on_mobile(self):
        css = (ROOT / "admin" / "admin.css").read_text()
        self.assertIn("Responsive adaptive layer v1", css)
        self.assertIn("aside nav{display:flex!important", css)
        self.assertIn("overflow-x:auto", css)
        self.assertIn("@media(max-width:520px)", css)

    def test_customer_contact_and_app_pages_are_responsive(self):
        customer = (ROOT / "customer_http.py").read_text()
        contact = (ROOT / "contact_request.py").read_text()
        app = (ROOT / "app_download.py").read_text()
        for source in (customer, contact, app):
            self.assertIn("viewport-fit=cover", source)
        self.assertIn("@media(max-width:480px)", customer)
        self.assertIn("@media(max-width:520px)", contact)
        self.assertIn("@media(max-width:640px)", app)

    def test_mobile_navigation_exists_without_hiding_customer_access(self):
        page = (ROOT / "index.html").read_text()
        self.assertIn('<details class="mobile-navigation">', page)
        self.assertIn('aria-label="Navigation mobile"', page)
        self.assertIn('/app.js?v=responsive-4', page)

    def test_booking_cta_is_visible_before_slot_selection_and_phone_is_secondary(self):
        page = (ROOT / "index.html").read_text()
        source = (ROOT / "app.js").read_text()
        config = (ROOT / "data" / "site-config.json").read_text()
        self.assertIn('class="booking-selection booking-awaiting"', page)
        self.assertNotIn('class="booking-selection" hidden', page)
        self.assertIn("Sélectionnez un créneau ci-dessus", page)
        self.assertIn("Les contrôles à 80 € et 90 € se réservent directement ci-dessus.", page)
        self.assertNotIn("Réservation uniquement par téléphone.", page)
        self.assertIn("01 86 04 68 64", page)
        self.assertIn("+33186046864", page)
        self.assertIn("01 86 04 68 64", config)
        self.assertNotIn("box.hidden=true", source)
        self.assertIn("box.classList.add('booking-awaiting')", source)
        self.assertIn("cta.classList.remove('disabled')", source)

    def test_essential_booking_is_never_hidden_by_reveal_observer(self):
        source = (ROOT / "app.js").read_text()
        self.assertNotIn("el.style.opacity='0'", source)
        self.assertNotIn('threshold:.12', source)
        self.assertIn("{threshold:0}", source)

    def test_glb_module_is_allowed_without_exposing_arbitrary_scripts(self):
        import security_guard
        self.assertTrue(security_guard.static_allowed('/assets/cybercheck-glb-hero.js'))
        self.assertFalse(security_guard.static_allowed('/assets/private-helper.js'))
        self.assertFalse(security_guard.static_allowed('/customer_http.py'))

    def test_static_admin_pages_use_safe_area_viewport(self):
        for relative in (
            "admin/index.html",
            "admin/payments.html",
            "admin/customers.html",
            "admin/compliance-registers.html",
        ):
            with self.subTest(relative=relative):
                page = (ROOT / relative).read_text()
                self.assertIn("viewport-fit=cover", page)


if __name__ == "__main__":
    unittest.main()
