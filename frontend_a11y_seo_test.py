"""F-02: control-type selector semantics and AutoRepair structured data."""
from html.parser import HTMLParser
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent


class _Roles(HTMLParser):
    def __init__(self):
        super().__init__(); self.stack = []; self.selector = None; self.buttons = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id") == "controlTypeSelector":
            self.selector = attrs
            self.stack.append(tag)
        elif self.stack:
            self.stack.append(tag)
            if tag == "button":
                self.buttons.append(attrs)

    def handle_endtag(self, tag):
        if self.stack:
            self.stack.pop()


class FrontendA11ySeoTest(unittest.TestCase):
    def test_control_type_selector_roles_are_consistent(self):
        parser = _Roles(); parser.feed((ROOT / "index.html").read_text(encoding="utf-8"))
        self.assertIsNotNone(parser.selector)
        self.assertEqual(len(parser.buttons), 2)
        if parser.selector.get("role") == "radiogroup":
            for button in parser.buttons:
                self.assertEqual(button.get("role"), "radio")
                self.assertIn("aria-checked", button)
        else:
            for button in parser.buttons:
                self.assertIn("aria-pressed", button)

    def test_structured_data_uses_automotive_type_and_image(self):
        import admin_server
        data = admin_server.build_structured_data(admin_server.load_config())
        self.assertEqual(data["@type"], "AutoRepair")
        self.assertTrue(data.get("image", "").startswith(("https://", "/")))


    def test_structured_data_geo_matches_the_public_directions_link(self):
        import re
        import admin_server
        data = admin_server.build_structured_data(admin_server.load_config())
        self.assertEqual(data["geo"]["@type"], "GeoCoordinates")
        html = (Path(admin_server.__file__).resolve().parent / "index.html").read_text(encoding="utf-8")
        lat, lon = re.search(r"destination=([0-9.]+)%2C([0-9.]+)", html).groups()
        self.assertEqual(f'{data["geo"]["latitude"]:.6f}', lat)
        self.assertEqual(f'{data["geo"]["longitude"]:.6f}', lon)
        self.assertIn(f"mlat={lat}&mlon={lon}", data["hasMap"])

if __name__ == "__main__":
    unittest.main()
