import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


class AdminGoogleErrorSanitizationTest(unittest.TestCase):
    def _probe(self, source):
        root = Path(tempfile.mkdtemp(prefix='cybercheck-google-boundary-test-'))
        private = root / 'private'
        private.mkdir(parents=True)
        (private / 'admin-password').write_text('unit-test-password\n')
        env = dict(os.environ)
        env['CYBERCHECK_PRIVATE_DIR'] = str(private)
        env['CYBERCHECK_SECURITY_DIR'] = str(private / 'security')
        env['CYBERCHECK_DATA_DIR'] = str(root / 'data')
        result = subprocess.run(
            [sys.executable, '-c', textwrap.dedent(source)],
            cwd=Path(__file__).resolve().parent,
            env=env,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_public_oauth_callback_never_renders_exception_text(self):
        self._probe(r'''
            from unittest import mock
            import admin_server

            marker = 'someone@example.invalid SENSITIVE_MARKER_7f3a'
            h = object.__new__(admin_server.Handler)
            h.path = '/api/integrations/google/oauth/callback?state=s&code=c'
            h.command = 'GET'
            h._guard = lambda: True
            h._request_origin = lambda: 'https://www.checkupauto.fr'
            captured = {}
            h.send_bytes = lambda data, ctype, status=200, cache='no-store': captured.update(
                data=data, ctype=ctype, status=status, cache=cache
            )
            with mock.patch.object(admin_server.integrations, 'handle_oauth_callback', side_effect=RuntimeError(marker)):
                admin_server.Handler.do_GET(h)
            body = captured['data'].decode('utf-8')
            assert captured['status'] == 400
            assert 'someone@example.invalid' not in body
            assert 'SENSITIVE_MARKER_7f3a' not in body
            assert 'La connexion Google n’a pas pu être finalisée.' in body
        ''')

    def test_google_integration_status_returns_bounded_error_code(self):
        self._probe(r'''
            from unittest import mock
            import admin_server

            marker = 'someone@example.invalid SENSITIVE_MARKER_7f3a'
            h = object.__new__(admin_server.Handler)
            h.path = '/api/admin/integrations/google/status'
            h.command = 'GET'
            h._guard = lambda: True
            h._request_origin = lambda: 'https://www.checkupauto.fr'
            h.authorized = lambda: True
            captured = {}
            h.send_json = lambda obj, status=200: captured.update(obj=obj, status=status)
            with mock.patch.object(admin_server.gsc, 'credential_info', return_value={}), \
                 mock.patch.object(admin_server.integrations, 'status', side_effect=RuntimeError(marker)):
                admin_server.Handler.do_GET(h)
            assert captured['status'] == 500
            assert captured['obj'] == {'ok': False, 'error': 'google_integration_status_unavailable'}
            serialized = repr(captured['obj'])
            assert 'someone@example.invalid' not in serialized
            assert 'SENSITIVE_MARKER_7f3a' not in serialized
        ''')

    def test_all_google_boundary_blocks_reject_exception_serialization(self):
        source = Path('admin_server.py').read_text()

        def block(start, end, offset=0):
            i = source.find(start, offset)
            j = source.find(end, i)
            self.assertGreaterEqual(i, 0, start)
            self.assertGreaterEqual(j, 0, end)
            return source[i:j]

        callback = block(
            "  if path=='/api/integrations/google/oauth/callback':",
            "  if path=='/api/admin/readiness':")
        self.assertNotIn('esc(exc)', callback)
        self.assertIn('La connexion Google n’a pas pu être finalisée.', callback)

        status = block(
            "  if path=='/api/admin/integrations/google/status':",
            "  if path=='/api/admin/referrals/accounts':")
        self.assertNotIn('str(exc)', status)
        self.assertIn('google_integration_status_unavailable', status)

        google_get = block(
            "  if path.startswith('/api/admin/google/'):",
            "  if path.startswith('/p/'):")
        self.assertNotIn('str(exc)', google_get)
        self.assertIn('google_search_console_unavailable', google_get)

        post = source.find(' def do_POST(self):')
        integration_post = block(
            "  if path=='/api/admin/integrations/google/oauth-client':",
            "  if path=='/api/admin/mercure/login':", post)
        self.assertNotIn('str(exc)', integration_post)
        self.assertIn('google_integration_request_failed', integration_post)

        google_post = block(
            "  if path.startswith('/api/admin/google/'):",
            "  if path!='/api/admin/config':", post)
        self.assertNotIn('str(exc)', google_post)
        self.assertIn('google_search_console_request_failed', google_post)

        delete = source.find(' def do_DELETE(self):')
        google_delete = block(
            "  if path=='/api/admin/integrations/google/oauth':",
            "  if path=='/api/admin/mercure/promo-slot':", delete)
        self.assertNotIn('str(exc)', google_delete)
        self.assertIn('google_request_failed', google_delete)


if __name__ == '__main__':
    unittest.main()
