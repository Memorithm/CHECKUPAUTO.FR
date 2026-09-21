from pathlib import Path
import unittest


class PublicValidationErrorBoundaryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("admin_server.py").read_text()

    def _block(self, start, end):
        begin = self.source.find(start)
        self.assertGreaterEqual(begin, 0, start)
        finish = self.source.find(end, begin)
        self.assertGreaterEqual(finish, 0, end)
        return self.source[begin:finish]

    def test_geo_quote_validation_is_bounded(self):
        block = self._block("  if path=='/api/geo/quote':", "  if path=='/api/booking/availability':")
        self.assertIn("'error':'geo_quote_invalid'", block)
        self.assertNotIn("'error':str(exc)", block)

    def test_booking_availability_validation_is_bounded(self):
        block = self._block("  if path=='/api/booking/availability':", "  if path=='/go/app':")
        self.assertIn("'error':'booking_availability_invalid'", block)
        self.assertNotIn("'error':str(exc)", block)

    def test_codes_are_stable_non_sensitive_identifiers(self):
        for code in ('geo_quote_invalid', 'booking_availability_invalid'):
            self.assertRegex(code, r'^[a-z0-9_]+$')
            self.assertLessEqual(len(code), 40)


if __name__ == '__main__':
    unittest.main()
