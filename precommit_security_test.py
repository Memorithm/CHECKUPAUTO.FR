import unittest

from scripts import precommit_security as security


class PrecommitSecurityTest(unittest.TestCase):
    def assert_detected(self, expected_name, value):
        findings = security.scan_text('fixture.txt', value)
        self.assertIn(f'{expected_name}: fixture.txt', findings)

    def test_detects_google_api_key(self):
        value = 'AI' + 'za' + ('A' * 35)
        self.assert_detected('google-api-key', value)

    def test_detects_google_oauth_client_secret(self):
        value = 'GOC' + 'SPX-' + ('B' * 28)
        self.assert_detected('google-oauth-client-secret', value)

    def test_detects_google_access_token(self):
        value = 'ya' + '29.' + ('C' * 48)
        self.assert_detected('google-access-token', value)

    def test_does_not_flag_google_identifiers_or_scope_urls(self):
        benign = '\n'.join([
            'client-id.apps.googleusercontent.com',
            'https://www.googleapis.com/auth/webmasters',
            'https://oauth2.googleapis.com/token',
        ])
        google_findings = [
            item for item in security.scan_text('fixture.txt', benign)
            if item.startswith('google-')
        ]
        self.assertEqual(google_findings, [])


if __name__ == '__main__':
    unittest.main()
