"""Real Handler HTTP tests with isolated storage and no payment provider calls."""
import base64
import contextlib
import http.client
import importlib
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch


@unittest.skipUnless(Path(__file__).with_name('admin_server.py').exists(), 'requires full application tree')
class PaymentContractRoutesTest(unittest.TestCase):
    @contextlib.contextmanager
    def server(self, mfa=True):
        with tempfile.TemporaryDirectory() as private:
            Path(private, 'admin-password').write_text('synthetic-test-password\n')
            with patch.dict(os.environ, {'CYBERCHECK_PRIVATE_DIR': private, 'CYBERCHECK_DATA_DIR': private,
                                       'CYBERCHECK_SECURITY_DIR': str(Path(private, 'security'))}):
                app = importlib.import_module('admin_server')
                with patch.object(app.Handler, '_guard', return_value=True), \
                     patch.object(app.Handler, '_mfa_session_valid', return_value=mfa):
                    httpd = app.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
                    thread = threading.Thread(target=httpd.serve_forever, daemon=True); thread.start()
                    credentials = base64.b64encode((app.USER + ':' + app.PASSWORD).encode()).decode()
                    try:
                        yield httpd.server_address, 'Basic ' + credentials, Path(private)
                    finally:
                        httpd.shutdown(); httpd.server_close(); thread.join(timeout=5)

    def request(self, address, authorization='', payload=None, token='', path='/api/admin/payments/contract'):
        connection = http.client.HTTPConnection(*address, timeout=5)
        headers = {'Content-Type': 'application/json', 'Origin': 'http://' + address[0] + ':' + str(address[1])}
        if authorization: headers['Authorization'] = authorization
        if token: headers['X-CheckupAuto-Payments-CSRF'] = token
        body = None if payload is None else json.dumps(payload).encode()
        try:
            connection.request('GET' if payload is None else 'POST', path, body, headers)
            response = connection.getresponse(); raw = response.read()
            return response.status, dict(response.getheaders()), json.loads(raw) if raw.startswith(b'{') else raw
        finally:
            connection.close()

    def test_auth_challenge_and_mfa_precede_private_storage(self):
        with self.server() as (address, authorization, private):
            status, headers, body = self.request(address)
            self.assertEqual(status, 401)
            self.assertIn('WWW-Authenticate', headers)
            self.assertFalse((private / 'payments').exists())
        with self.server(mfa=False) as (address, authorization, private):
            status, _, body = self.request(address, authorization)
            self.assertEqual(status, 403)
            self.assertEqual(body['error'], 'two_factor_required')
            self.assertFalse((private / 'payments').exists())

    def test_editor_roundtrip_csrf_and_conflict_on_real_http_routes(self):
        with self.server() as (address, authorization, private):
            status, headers, data = self.request(address, authorization)
            self.assertEqual(status, 200)
            self.assertEqual(headers['Cache-Control'], 'no-store')
            payload = {'revision': 0, 'mode': 'manual', 'fields': {'platform': 'Payline Monext', 'nlsa': '001'}}
            self.assertEqual(self.request(address, authorization, payload)[0], 403)
            status, _, saved = self.request(address, authorization, payload, data['csrfToken'])
            self.assertEqual(status, 200)
            self.assertEqual(saved['fields']['nlsa'], '001')
            self.assertFalse(saved['status']['livePaymentsEnabled'])
            self.assertEqual(self.request(address, authorization, payload, saved['csrfToken'])[0], 409)
            self.assertEqual(self.request(address, authorization)[2]['fields']['nlsa'], '001')
            self.assertTrue((private / 'payments' / 'contract.enc').exists())

    def test_runtime_status_is_secret_free_and_live_payments_remain_closed(self):
        with self.server() as (address, authorization, private):
            status, _, body = self.request(address, authorization)
            self.assertEqual(status, 200)
            runtime = body["runtime"]
            self.assertEqual(runtime["provider"], "payline")
            self.assertTrue(runtime["transportImplemented"])
            self.assertFalse(runtime["livePaymentsEnabled"])
            self.assertTrue(runtime["checkoutBound"])
            self.assertTrue(runtime["checkoutBasis"]["authoritativeBookingBound"])
            self.assertTrue(runtime["checkoutBasis"]["serverAuthoritativePrice"])
            self.assertTrue(runtime["checkoutBasis"]["contractAcceptanceBound"])
            self.assertTrue(runtime["checkoutBasis"]["publicStartRouteBound"])
            self.assertNotIn("merchantId", repr(runtime))
            self.assertNotIn("accessKey", repr(runtime))
            self.assertNotIn("contractNumber", repr(runtime))


    def test_activity_route_is_authenticated_minimized_and_empty_by_default(self):
        with self.server() as (address, authorization, private):
            status, _, body = self.request(
                address,
                authorization,
                path='/api/admin/payments/activity',
            )
            self.assertEqual(status, 200)
            self.assertTrue(body['ok'])
            self.assertEqual(body['summary']['total'], 0)
            self.assertEqual(body['transactions'], [])
            self.assertNotIn('booking_reference', repr(body))
            self.assertNotIn('provider_reference', repr(body))

    def test_http_validation_never_returns_submitted_secret(self):
        with self.server() as (address, authorization, private):
            data = self.request(address, authorization)[2]
            status, _, body = self.request(address, authorization,
                {'revision': 0, 'mode': 'manual', 'fields': {'accessKey': 'private-synthetic-secret'}}, data['csrfToken'])
            self.assertEqual(status, 400)
            self.assertNotIn('private-synthetic-secret', repr(body))
            self.assertFalse((private / 'payments' / 'contract.enc').exists())


if __name__ == '__main__':
    unittest.main()
