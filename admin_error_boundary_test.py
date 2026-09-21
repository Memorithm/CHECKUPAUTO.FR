from pathlib import Path
import unittest


class AdminErrorBoundaryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("admin_server.py").read_text()

    def _block(self, start, end, offset=0):
        begin = self.source.find(start, offset)
        self.assertGreaterEqual(begin, 0, start)
        finish = self.source.find(end, begin)
        self.assertGreaterEqual(finish, 0, end)
        return self.source[begin:finish]

    def _bounded(self, block):
        self.assertNotIn("'error':str(exc)", block)
        self.assertNotIn("'error':type(exc).__name__", block)

    def test_admin_get_boundaries_are_bounded(self):
        core = self._block("  if path=='/api/admin/readiness':", "  if path=='/api/booking-test/status':")
        mercure = self._block("  if path.startswith('/api/admin/mercure/'):", "  if path.startswith('/api/admin/google/'):", self.source.find(' def do_GET(self):'))
        self._bounded(core); self._bounded(mercure)
        for code in ('readiness_unavailable','referral_admin_unavailable','notification_status_unavailable','security_status_unavailable','mercure_admin_request_failed'):
            self.assertIn(code, core + mercure)

    def test_admin_post_boundaries_are_bounded(self):
        post = self.source.find(' def do_POST(self):')
        core = self._block("  if path=='/api/admin/mobile/claims/issue':", "  if path.startswith('/api/admin/google/'):", post)
        config = self._block("  if path!='/api/admin/config':", " def do_DELETE(self):", post)
        self._bounded(core); self._bounded(config)
        for code in ('mobile_claim_not_found','referral_request_invalid','notification_preflight_failed','recipient_retry_unavailable','security_vulnerability_refresh_failed','mercure_secret_rotation_failed','config_update_invalid'):
            self.assertIn(code, core + config)

    def test_admin_delete_boundary_is_bounded(self):
        delete = self.source.find(' def do_DELETE(self):')
        block = self._block("  if path=='/api/admin/mercure/promo-slot':", "  return self.send_json({'error':'not_found'},404)", delete)
        self._bounded(block)
        self.assertIn('mercure_promotion_delete_failed', block)

    def test_no_synthetic_sensitive_marker_is_embedded(self):
        marker = 'sensitive-user@example.invalid:synthetic-token-marker'
        self.assertNotIn(marker, self.source)
        self.assertNotIn(marker, 'admin_request_failed')


if __name__ == '__main__':
    unittest.main()
