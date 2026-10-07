"""Contract checks for the mobile navigation application chooser."""
import html
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import unittest


class NavigationElements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements = {}

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        identity = values.get("id") or values.get("data-navigation-app")
        if identity in {"directionsOpen", "directionsDialog", "waze", "google", "apple", "android", "share"}:
            self.elements[identity] = (tag, values)


class NavigationPickerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = Path("index.html").read_text()
        cls.js = Path("app.js").read_text()
        cls.css = Path("style.css").read_text()
        parser = NavigationElements()
        parser.feed(cls.html)
        cls.elements = parser.elements

    def test_dialog_has_accessible_title_description_and_fallback(self):
        tag, button = self.elements["directionsOpen"]
        self.assertEqual(tag, "a")
        self.assertEqual(button.get("aria-haspopup"), "dialog")
        self.assertEqual(button.get("aria-controls"), "directionsDialog")
        self.assertEqual(button.get("target"), "_blank")
        tag, dialog = self.elements["directionsDialog"]
        self.assertEqual(tag, "dialog")
        self.assertEqual(dialog.get("aria-labelledby"), "directionsDialogTitle")
        self.assertEqual(dialog.get("aria-describedby"), "directionsDialogDescription")
        self.assertIn("initDirectionsPicker();", self.js)
        self.assertIn("typeof dialog.showModal!=='function'", self.js)
        self.assertIn("dialog.addEventListener('close'", self.js)
        self.assertIn("prefers-reduced-motion:reduce", self.css)

    def test_all_navigation_links_use_centre_coordinates(self):
        for name in ("google", "waze", "apple", "android"):
            tag, attrs = self.elements[name]
            self.assertEqual(tag, "a")
            url = urlparse(html.unescape(attrs["href"]))
            params = parse_qs(url.query)
            if name == "waze":
                self.assertEqual(url.netloc, "waze.com")
                self.assertEqual(params["ll"], ["48.980120,1.890251"])
                self.assertEqual(params["navigate"], ["yes"])
            elif name == "apple":
                self.assertEqual(url.netloc, "maps.apple.com")
                self.assertEqual(params["daddr"], ["48.980120,1.890251"])
                self.assertEqual(params["dirflg"], ["d"])
            elif name == "google":
                self.assertEqual(url.netloc, "www.google.com")
                self.assertEqual(params["destination"], ["48.980120,1.890251"])
                self.assertEqual(params["travelmode"], ["driving"])
            else:
                self.assertEqual(url.scheme, "geo")
                self.assertEqual(params["q"], ["48.980120,1.890251"])
                self.assertIn("hidden", attrs)

    def test_native_app_choice_is_not_misrepresented_as_installation_detection(self):
        self.assertIn('android.hidden=!isAndroid', self.js)
        self.assertIn("share.hidden=isAndroid||typeof navigator.share!=='function'", self.js)
        self.assertIn("dialog.showModal()", self.js)
        self.assertIn("dialog.close()", self.js)
        self.assertIn("Le choix d’une application ne garantit pas son installation", self.html)


if __name__ == "__main__":
    unittest.main()
