from pathlib import Path
import unittest


class PublicPermissionErrorBoundaryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("admin_server.py").read_text()

    def test_booking_test_status_permission_error_is_bounded(self):
        start = self.source.find("  if path=='/api/booking-test/status':")
        end = self.source.find("  if path=='/api/booking/services':", start)
        self.assertGreaterEqual(start, 0)
        self.assertGreaterEqual(end, 0)
        block = self.source[start:end]
        self.assertIn("except PermissionError: return self.send_json({'ok':False,'error':'booking_test_forbidden'},403)", block)
        self.assertNotIn("str(exc)", block)

    def test_public_post_permission_errors_are_bounded(self):
        post = self.source.find(' def do_POST(self):')
        self.assertGreaterEqual(post, 0)
        start = self.source.find("  if path=='/api/integrations/mercure/browser-confirmed':", post)
        end = self.source.find("  if path.startswith('/api/admin/'):", start)
        self.assertGreaterEqual(start, 0)
        self.assertGreaterEqual(end, 0)
        block = self.source[start:end]
        self.assertNotIn("except PermissionError as exc: return self.send_json({'ok':False,'error':str(exc)}", block)
        self.assertEqual(block.count("'error':'mercure_browser_confirmation_denied'"), 1)
        self.assertEqual(block.count("'error':'mobile_request_forbidden'"), 7)
        self.assertEqual(block.count("'error':'booking_test_forbidden'"), 2)

    def test_permission_codes_do_not_embed_exception_details(self):
        for code in ('mercure_browser_confirmation_denied','mobile_request_forbidden','booking_test_forbidden'):
            self.assertNotIn('@', code)
            self.assertNotIn(':', code)
            self.assertLessEqual(len(code), 40)


if __name__ == '__main__':
    unittest.main()
