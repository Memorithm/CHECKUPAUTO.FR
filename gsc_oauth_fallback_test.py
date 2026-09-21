import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import gsc_client as gsc


class GSCOAuthFallbackTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_creds = gsc.CREDS
        gsc.CREDS = Path(self.tmp.name) / 'gsc-service-account.json'
        gsc.CREDS.write_text(json.dumps({'type': 'service_account'}))

    def tearDown(self):
        gsc.CREDS = self.original_creds
        self.tmp.cleanup()

    def test_invalid_static_file_does_not_mask_usable_oauth_status(self):
        with patch('gsc_client.integrations.has_usable_scopes', return_value=True), patch(
            'gsc_client.integrations.oauth_client_info',
            return_value={'projectId': 'oauth-project'},
        ):
            info = gsc.credential_info()
        self.assertTrue(info['configured'])
        self.assertEqual(info['mode'], 'oauth')
        self.assertTrue(info['serviceAccountInvalid'])
        self.assertEqual(info['projectId'], 'oauth-project')

    def test_invalid_static_file_falls_back_to_oauth_access_token(self):
        with patch(
            'gsc_client.integrations.google_access_token', return_value='oauth-access'
        ) as oauth, patch(
            'gsc_client.service_account.Credentials.from_service_account_file'
        ) as static_loader:
            token = gsc._access_token()
        self.assertEqual(token, 'oauth-access')
        oauth.assert_called_once_with(gsc.SCOPES)
        static_loader.assert_not_called()

    def test_valid_static_file_still_takes_precedence(self):
        gsc.CREDS.write_text(json.dumps({
            'type': 'service_account',
            'client_email': 'search-console@example.invalid',
            'private_key': 'not-a-real-private-key',
            'token_uri': gsc.TOKEN_URL,
            'project_id': 'static-project',
        }))
        fake_creds = unittest.mock.Mock()
        fake_creds.token = 'static-access'
        with patch(
            'gsc_client.service_account.Credentials.from_service_account_file',
            return_value=fake_creds,
        ) as static_loader, patch(
            'gsc_client.integrations.google_access_token'
        ) as oauth:
            token = gsc._access_token()
        self.assertEqual(token, 'static-access')
        static_loader.assert_called_once()
        oauth.assert_not_called()


if __name__ == '__main__':
    unittest.main()
