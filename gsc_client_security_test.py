import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

import gsc_client as gsc
import integration_hub as integrations


class GSCClientSecurityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_creds = gsc.CREDS
        gsc.CREDS = Path(self.tmp.name) / 'gsc-service-account.json'

    def tearDown(self):
        gsc.CREDS = self.original_creds
        self.tmp.cleanup()

    def _service_account_payload(self, token_uri=gsc.TOKEN_URL):
        return {
            'type': 'service_account',
            'client_email': 'service@example.invalid',
            'private_key': '-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----\n',
            'token_uri': token_uri,
            'project_id': 'cybercheck-test',
        }

    def test_unapproved_service_account_token_uri_is_rejected(self):
        with self.assertRaisesRegex(gsc.GSCError, 'token_uri Google non approuvée'):
            gsc.save_credentials(
                self._service_account_payload(
                    'https://attacker.invalid/token?secret=bearer-super-secret'
                )
            )
        self.assertFalse(gsc.CREDS.exists())

    def test_http_error_body_is_not_exposed(self):
        response = Mock()
        response.status_code = 503
        response.headers = {'Retry-After': '45'}
        response.content = b'{"error": {"message": "secret"}}'
        response.json.return_value = {
            'error': {
                'message': 'client@example.fr bearer-super-secret',
            }
        }
        response.text = 'client@example.fr bearer-super-secret'
        with patch('gsc_client._access_token', return_value='access-token'):
            with patch('gsc_client.requests.request', return_value=response):
                with self.assertRaises(gsc.GSCError) as caught:
                    gsc._request('GET', gsc.WEBMASTERS + '/sites')
        exc = caught.exception
        self.assertEqual(str(exc), 'Google Search Console a refusé la requête.')
        self.assertEqual(exc.status, 503)
        self.assertEqual(exc.retry_after, '45')
        self.assertTrue(exc.retryable)
        self.assertNotIn('client@example.fr', str(exc))
        self.assertNotIn('bearer-super-secret', str(exc))

    def test_network_error_is_sanitized(self):
        external = requests.ConnectionError(
            'proxy user:pass@example.invalid bearer-super-secret'
        )
        with patch('gsc_client._access_token', return_value='access-token'):
            with patch('gsc_client.requests.request', side_effect=external):
                with self.assertRaises(gsc.GSCError) as caught:
                    gsc._request('GET', gsc.WEBMASTERS + '/sites')
        exc = caught.exception
        self.assertEqual(str(exc), 'Connexion à Google Search Console impossible.')
        self.assertTrue(exc.retryable)
        self.assertNotIn('user:pass', str(exc))
        self.assertNotIn('bearer-super-secret', str(exc))

    def test_malformed_success_response_is_sanitized(self):
        response = Mock()
        response.status_code = 200
        response.headers = {}
        response.content = b'not-json'
        response.json.side_effect = ValueError(
            'client@example.fr bearer-super-secret'
        )
        with patch('gsc_client._access_token', return_value='access-token'):
            with patch('gsc_client.requests.request', return_value=response):
                with self.assertRaises(gsc.GSCError) as caught:
                    gsc._request('GET', gsc.WEBMASTERS + '/sites')
        self.assertEqual(str(caught.exception), 'Réponse Google Search Console invalide.')
        self.assertNotIn('client@example.fr', str(caught.exception))
        self.assertNotIn('bearer-super-secret', str(caught.exception))

    def test_service_account_authentication_failure_is_sanitized(self):
        gsc.CREDS.write_text(json.dumps(self._service_account_payload()))
        external = RuntimeError('client@example.fr bearer-super-secret')
        with patch(
            'gsc_client.service_account.Credentials.from_service_account_file',
            side_effect=external,
        ):
            with self.assertRaises(gsc.GSCError) as caught:
                gsc._access_token()
        exc = caught.exception
        self.assertEqual(
            str(exc),
            'Authentification du compte de service Search Console impossible.',
        )
        self.assertTrue(exc.retryable)
        self.assertNotIn('client@example.fr', str(exc))
        self.assertNotIn('bearer-super-secret', str(exc))

    def test_oauth_http_failure_preserves_only_bounded_metadata(self):
        external = integrations.IntegrationHTTPError(
            'client@example.fr bearer-super-secret',
            status=429,
            retry_after='30',
            retryable=True,
        )
        with patch('gsc_client.integrations.google_access_token', side_effect=external):
            with self.assertRaises(gsc.GSCError) as caught:
                gsc._access_token()
        exc = caught.exception
        self.assertEqual(
            str(exc),
            'Autorisation Google Search Console temporairement indisponible.',
        )
        self.assertEqual(exc.status, 429)
        self.assertEqual(exc.retry_after, '30')
        self.assertTrue(exc.retryable)
        self.assertNotIn('client@example.fr', str(exc))
        self.assertNotIn('bearer-super-secret', str(exc))


if __name__ == '__main__':
    unittest.main()
