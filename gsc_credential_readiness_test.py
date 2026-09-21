import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import gsc_client as gsc


class GSCCredentialReadinessTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_creds = gsc.CREDS
        gsc.CREDS = Path(self.tmp.name) / 'gsc-service-account.json'

    def tearDown(self):
        gsc.CREDS = self.original_creds
        self.tmp.cleanup()

    def _write(self, payload):
        gsc.CREDS.write_text(json.dumps(payload))

    def _valid_payload(self):
        return {
            'type': 'service_account',
            'client_email': 'search-console@example.invalid',
            'private_key': 'not-a-real-private-key',
            'token_uri': gsc.TOKEN_URL,
            'project_id': 'checkupauto-test',
        }

    def test_empty_json_is_not_reported_configured(self):
        self._write({})
        with patch('gsc_client.integrations.has_usable_scopes', return_value=False):
            info = gsc.credential_info()
        self.assertFalse(info['configured'])
        self.assertEqual(info['mode'], 'service_account_invalid')
        self.assertIsNone(info['clientEmail'])
        self.assertIsNone(info['projectId'])

    def test_missing_private_key_is_not_reported_configured(self):
        payload = self._valid_payload()
        payload.pop('private_key')
        self._write(payload)
        info = gsc.credential_info()
        self.assertFalse(info['configured'])
        self.assertEqual(info['mode'], 'service_account_invalid')

    def test_untrusted_token_uri_is_not_reported_configured(self):
        payload = self._valid_payload()
        payload['token_uri'] = 'https://attacker.invalid/token'
        self._write(payload)
        info = gsc.credential_info()
        self.assertFalse(info['configured'])
        self.assertEqual(info['mode'], 'service_account_invalid')

    def test_valid_static_shape_is_reported_configured(self):
        self._write(self._valid_payload())
        info = gsc.credential_info()
        self.assertTrue(info['configured'])
        self.assertEqual(info['mode'], 'service_account')
        self.assertEqual(info['clientEmail'], 'search-console@example.invalid')
        self.assertEqual(info['projectId'], 'checkupauto-test')


if __name__ == '__main__':
    unittest.main()
