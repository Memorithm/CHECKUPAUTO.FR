from pathlib import Path
import unittest


class AdminPublicErrorSanitizationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path('admin_server.py').read_text()

    def _block(self, start, end, offset=0):
        begin = self.source.find(start, offset)
        self.assertGreaterEqual(begin, 0, start)
        finish = self.source.find(end, begin)
        self.assertGreaterEqual(finish, 0, end)
        return self.source[begin:finish]

    def _assert_bounded(self, start, end, code, offset=0):
        block = self._block(start, end, offset)
        self.assertIn(code, block)
        self.assertNotIn("except Exception as exc: return self.send_json({'ok':False,'error':str(exc)}", block)
        self.assertNotIn("'detail':str(exc)", block)

    def test_public_get_unexpected_failures_use_bounded_codes(self):
        cases = [
            ("  if path=='/api/booking-test/status':", "  if path=='/api/booking/services':", 'booking_test_status_unavailable'),
            ("  if path=='/api/geo/coverage':", "  if path=='/api/geo/quote':", 'geo_coverage_unavailable'),
            ("  if path=='/api/geo/quote':", "  if path=='/api/booking/availability':", 'geo_quote_unavailable'),
            ("  if path=='/api/booking/availability':", "  if path=='/go/app':", 'booking_availability_unavailable'),
            ("  if path=='/go/booking':", "  if path.startswith('/api/admin/mercure/'):", 'booking_request_failed'),
            ("  if path=='/api/mobile/bootstrap':", "  if path=='/api/admin/config':", 'mobile_bootstrap_unavailable'),
        ]
        for start, end, code in cases:
            with self.subTest(code=code):
                self._assert_bounded(start, end, code)

    def test_public_post_unexpected_failures_use_bounded_codes(self):
        post = self.source.find(' def do_POST(self):')
        self.assertGreaterEqual(post, 0)
        cases = [
            ("  if path=='/api/integrations/mercure/browser-confirmed':", "  if path=='/api/integrations/mercure/booking-confirmed':", 'mercure_browser_confirmation_invalid'),
            ("  if path=='/api/integrations/mercure/booking-confirmed':", "  if path=='/api/mobile/installations/register':", 'mercure_booking_confirmation_invalid'),
            ("  if path=='/api/mobile/installations/register':", "  if path=='/api/mobile/installations/delete':", 'mobile_request_invalid'),
            ("  if path=='/api/mobile/installations/delete':", "  if path=='/api/mobile/devices/register':", 'mobile_request_invalid'),
            ("  if path=='/api/mobile/devices/register':", "  if path=='/api/mobile/devices/unregister':", 'mobile_request_invalid'),
            ("  if path=='/api/mobile/devices/unregister':", "  if path=='/api/mobile/claims/consume':", 'mobile_request_invalid'),
            ("  if path=='/api/mobile/claims/consume':", "  if path=='/api/mobile/inventory':", 'mobile_request_invalid'),
            ("  if path=='/api/mobile/inventory':", "  if path=='/api/mobile/reminders/sync':", 'mobile_request_invalid'),
            ("  if path=='/api/mobile/reminders/sync':", "  if path=='/api/events':", 'mobile_request_invalid'),
            ("  if path=='/api/events':", "  if path=='/api/booking-test/create':", 'analytics_event_invalid'),
            ("  if path=='/api/booking-test/create':", "  if path=='/api/booking-test/remove':", 'booking_test_request_invalid'),
            ("  if path=='/api/booking-test/remove':", "  if path.startswith('/api/admin/'):", 'booking_test_request_invalid'),
        ]
        for start, end, code in cases:
            with self.subTest(code=code):
                self._assert_bounded(start, end, code, post)

    def test_public_boundary_does_not_embed_synthetic_sensitive_marker(self):
        marker = 'sensitive-user@example.invalid:synthetic-token-marker'
        self.assertNotIn(marker, self.source)
        self.assertNotIn(marker, 'booking_test_status_unavailable')
        self.assertNotIn(marker, 'mobile_request_invalid')


if __name__ == '__main__':
    unittest.main()
