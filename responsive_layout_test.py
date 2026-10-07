from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent


class ResponsiveLayoutTest(unittest.TestCase):
    def test_public_page_uses_safe_area_viewport_and_cache_busted_css(self):
        page = (ROOT / "index.html").read_text()
        self.assertIn("width=device-width,initial-scale=1,viewport-fit=cover", page)
        self.assertIn("/style.css?v=responsive-1", page)

    def test_public_css_covers_phone_tablet_and_touch_layouts(self):
        css = (ROOT / "style.css").read_text()
        self.assertIn("Responsive adaptive layer v1", css)
        for breakpoint in ("@media(max-width:760px)", "@media(max-width:640px)", "@media(max-width:480px)", "@media(max-width:360px)"):
            self.assertIn(breakpoint, css)
        self.assertIn(".vehicle-option{flex:0 0 100%", css)
        self.assertIn(".booking-slots{grid-template-columns:1fr}", css)
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
