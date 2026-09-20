from pathlib import Path
import unittest


class AdminGoogleErrorSanitizationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path('admin_server.py').read_text()

    def _block(self, start, end, offset=0):
        begin = self.source.find(start, offset)
        self.assertGreaterEqual(begin, 0, start)
        finish = self.source.find(end, begin)
        self.assertGreaterEqual(finish, 0, end)
        return self.source[begin:finish]

    def test_public_oauth_callback_never_renders_exception_text(self):
        block = self._block(
            "  if path=='/api/integrations/google/oauth/callback':",
            "  if path=='/api/admin/readiness':",
        )
        self.assertNotIn('esc(exc)', block)
        self.assertNotIn('str(exc)', block)
        self.assertNotIn('except Exception as exc:', block)
        self.assertIn('La connexion Google n’a pas pu être finalisée.', block)

    def test_google_integration_status_uses_bounded_error_code(self):
        block = self._block(
            "  if path=='/api/admin/integrations/google/status':",
            "  if path=='/api/admin/referrals/accounts':",
        )
        self.assertNotIn('str(exc)', block)
        self.assertNotIn('except Exception as exc:', block)
        self.assertIn("'error':'google_integration_status_unavailable'", block)

    def test_search_console_get_and_post_use_bounded_error_codes(self):
        get_block = self._block(
            "  if path.startswith('/api/admin/google/'):",
            "  if path.startswith('/p/'):",
        )
        self.assertNotIn('str(exc)', get_block)
        self.assertIn("'error':'google_search_console_unavailable'", get_block)

        post = self.source.find(' def do_POST(self):')
        self.assertGreaterEqual(post, 0)
        integration_block = self._block(
            "  if path=='/api/admin/integrations/google/oauth-client':",
            "  if path=='/api/admin/mercure/login':",
            post,
        )
        self.assertNotIn('str(exc)', integration_block)
        self.assertIn("'error':'google_integration_request_failed'", integration_block)

        search_console_block = self._block(
            "  if path.startswith('/api/admin/google/'):",
            "  if path!='/api/admin/config':",
            post,
        )
        self.assertNotIn('str(exc)', search_console_block)
        self.assertIn("'error':'google_search_console_request_failed'", search_console_block)

    def test_google_delete_boundaries_use_bounded_error_codes(self):
        delete = self.source.find(' def do_DELETE(self):')
        self.assertGreaterEqual(delete, 0)
        block = self._block(
            "  if path=='/api/admin/integrations/google/oauth':",
            "  if path=='/api/admin/mercure/promo-slot':",
            delete,
        )
        self.assertNotIn('str(exc)', block)
        self.assertNotIn('except Exception as exc:', block)
        self.assertGreaterEqual(block.count("'error':'google_request_failed'"), 2)


if __name__ == '__main__':
    unittest.main()
