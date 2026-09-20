import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

_ROOT = Path(tempfile.mkdtemp(prefix='cybercheck-google-boundary-test-'))
_PRIVATE = _ROOT / 'private'
_PRIVATE.mkdir(parents=True)
(_PRIVATE / 'admin-password').write_text('unit-test-password\n')
os.environ['CYBERCHECK_PRIVATE_DIR'] = str(_PRIVATE)
os.environ['CYBERCHECK_SECURITY_DIR'] = str(_PRIVATE / 'security')
os.environ['CYBERCHECK_DATA_DIR'] = str(_ROOT / 'data')

import admin_server


class AdminGoogleErrorSanitizationTest(unittest.TestCase):
    def _handler(self, path):
        h = object.__new__(admin_server.Handler)
        h.path = path
        h.command = 'GET'
        h._guard = lambda: True
        h._request_origin = lambda: 'https://www.checkupauto.fr'
        return h

    def test_public_oauth_callback_never_renders_exception_text(self):
        marker = 'someone@example.invalid SENSITIVE_MARKER_7f3a'
        h = self._handler('/api/integrations/google/oauth/callback?state=s&code=c')
        captured = {}
        h.send_bytes = lambda data, ctype, status=200, cache='no-store': captured.update(
            data=data, ctype=ctype, status=status, cache=cache
        )
        with mock.patch.object(admin_server.integrations, 'handle_oauth_callback', side_effect=RuntimeError(marker)):
            admin_server.Handler.do_GET(h)
        body = captured['data'].decode('utf-8')
        self.assertEqual(captured['status'], 400)
        self.assertNotIn('someone@example.invalid', body)
        self.assertNotIn('SENSITIVE_MARKER_7f3a', body)
        self.assertIn('La connexion Google n’a pas pu être finalisée.', body)

    def test_google_integration_status_returns_bounded_error_code(self):
        marker = 'someone@example.invalid SENSITIVE_MARKER_7f3a'
        h = self._handler('/api/admin/integrations/google/status')
        h.authorized = lambda: True
        captured = {}
        h.send_json = lambda obj, status=200: captured.update(obj=obj, status=status)
        with mock.patch.object(admin_server.gsc, 'credential_info', return_value={}), \
             mock.patch.object(admin_server.integrations, 'status', side_effect=RuntimeError(marker)):
            admin_server.Handler.do_GET(h)
        self.assertEqual(captured['status'], 500)
        self.assertEqual(captured['obj'], {'ok': False, 'error': 'google_integration_status_unavailable'})
        self.assertNotIn('someone@example.invalid', repr(captured['obj']))
        self.assertNotIn('SENSITIVE_MARKER_7f3a', repr(captured['obj']))

    def test_all_google_boundary_blocks_reject_exception_serialization(self):
        source = Path('admin_server.py').read_text()
        def block(start, end, offset=0):
            i = source.find(start, offset)
            j = source.find(end, i)
            self.assertGreaterEqual(i, 0, start)
            self.assertGreaterEqual(j, 0, end)
            return source[i:j]

        self.assertNotIn('esc(exc)', block(
            "  if path=='/api/integrations/google/oauth/callback':",
            "  if path=='/api/admin/readiness':"))
        self.assertNotIn('str(exc)', block(
            "  if path=='/api/admin/integrations/google/status':",
            "  if path=='/api/admin/referrals/accounts':"))
        self.assertNotIn('str(exc)', block(
            "  if path.startswith('/api/admin/google/'):",
            "  if path.startswith('/p/'):"))
        post = source.find(' def do_POST(self):')
        self.assertNotIn('str(exc)', block(
            "  if path=='/api/admin/integrations/google/oauth-client':",
            "  if path=='/api/admin/mercure/login':", post))
        self.assertNotIn('str(exc)', block(
            "  if path.startswith('/api/admin/google/'):",
            "  if path!='/api/admin/config':", post))
        delete = source.find(' def do_DELETE(self):')
        self.assertNotIn('str(exc)', block(
            "  if path=='/api/admin/integrations/google/oauth':",
            "  if path=='/api/admin/mercure/promo-slot':", delete))


if __name__ == '__main__':
    unittest.main()
