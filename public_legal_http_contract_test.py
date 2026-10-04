from pathlib import Path
import unittest


class PublicLegalHttpContractTest(unittest.TestCase):
    def setUp(self):
        self.source = Path(__file__).with_name("admin_server.py").read_text(encoding="utf-8")

    def test_legal_head_responses_are_explicit_inline_html(self):
        start = self.source.index(" def do_HEAD(self):")
        end = self.source.index(" def render_index(self,c):", start)
        block = self.source[start:end]
        self.assertIn("if path in compliance.SLUG_TO_DOCUMENT:", block)
        self.assertIn("self.send_header('Content-Type','text/html; charset=utf-8')", block)
        self.assertIn("self.send_header('Content-Disposition','inline')", block)
        self.assertIn("'/go/booking'", block)

    def test_legal_get_responses_are_inline_html_not_json_downloads(self):
        get_start = self.source.index(" def do_GET(self):")
        start = self.source.index("  if path in compliance.SLUG_TO_DOCUMENT:", get_start)
        end = self.source.index("  if path=='/zone-tarifs':", start)
        block = self.source[start:end]
        self.assertGreaterEqual(block.count("'text/html; charset=utf-8'"), 2)
        self.assertGreaterEqual(block.count("headers={'Content-Disposition':'inline'}"), 2)
        self.assertNotIn("send_json(", block)
        self.assertNotIn("application/json", block)


if __name__ == "__main__":
    unittest.main()
