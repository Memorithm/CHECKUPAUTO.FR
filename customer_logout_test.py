"""Native logout must revoke only the current session and work without JavaScript."""
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

import analytics_store
import customer_accounts as accounts
import customer_http as http
import customer_http_test as support


class NativeCustomerLogoutTest(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix='checkupauto-logout-test-')
        self.addCleanup(temp.cleanup)
        root=Path(temp.name)
        env=patch.dict(os.environ,{
            'CYBERCHECK_DATA_DIR':str(root/'data'),
            'CYBERCHECK_PRIVATE_DIR':str(root/'private'),
            'CYBERCHECK_SECURITY_DIR':str(root/'security'),
        })
        env.start(); self.addCleanup(env.stop)
        db=patch.object(analytics_store,'DB',root/'analytics.sqlite3')
        db.start(); self.addCleanup(db.stop)
        self.account=accounts.create_from_verified_identity(
            'google','synthetic-logout','logout@example.test','Client Test',email_verified=True)
        self.token=accounts.issue_session(self.account['accountId'])['token']
        self.csrf=accounts.csrf_token(self.token)

    def handler(self,fields=None,headers=None,method='POST',cookie=True):
        raw=urlencode({'csrf':self.csrf} if fields is None else fields).encode()
        h=support.Handler(http.LOGOUT_FORM_ROUTE,method,headers={
            'Content-Type':'application/x-www-form-urlencoded',
            'Content-Length':str(len(raw)),
            'Cookie':f'{http.COOKIE_NAME}={self.token}' if cookie else '',
            **(headers or {}),
        })
        h.rfile=io.BytesIO(raw)
        return h

    def assert_active(self):
        self.assertEqual(accounts.authenticate_session(self.token),self.account['accountId'])

    def assert_redirect_and_cookie_clear(self,h):
        self.assertEqual(h.response['status'],303)
        self.assertEqual(h.response['headers']['Location'],'/compte')
        self.assertEqual(h.response['headers']['Cache-Control'],'no-store')
        cookie=h.response['headers']['Set-Cookie']
        for part in (http.COOKIE_NAME+'=;','Max-Age=0','Path=/','HttpOnly','Secure','SameSite=Lax'):
            self.assertIn(part,cookie)

    def test_native_post_revokes_session_and_returns_to_login(self):
        h=self.handler()
        self.assertTrue(http.handle(h))
        self.assert_redirect_and_cookie_clear(h)
        with self.assertRaises(PermissionError): accounts.authenticate_session(self.token)
        me=support.Handler(http.ME_ROUTE,headers={'Cookie':f'{http.COOKIE_NAME}={self.token}'})
        http.handle(me)
        self.assertEqual(me.response['status'],401)

    def test_logout_does_not_revoke_other_device_session(self):
        other=accounts.issue_session(self.account['accountId'])['token']
        http.handle(self.handler())
        self.assertEqual(accounts.authenticate_session(other),self.account['accountId'])

    def test_get_is_not_a_logout_action(self):
        h=self.handler(method='GET');http.handle(h)
        self.assertEqual(h.response['status'],405);self.assert_active()

    def test_cross_site_form_is_rejected(self):
        h=self.handler(headers={'Sec-Fetch-Site':'cross-site'});http.handle(h)
        self.assertEqual(h.response['status'],403);self.assert_active()

    def test_untrusted_origin_is_rejected(self):
        h=self.handler()
        with patch.object(h,'_admin_origin_ok',return_value=False):http.handle(h)
        self.assertEqual(h.response['status'],403);self.assert_active()

    def test_csrf_from_another_session_is_rejected(self):
        other=accounts.issue_session(self.account['accountId'])['token']
        h=self.handler({'csrf':accounts.csrf_token(other)});http.handle(h)
        self.assertEqual(h.response['status'],403);self.assert_active()

    def test_bad_or_empty_csrf_is_rejected(self):
        for value in ('','wrong'):
            with self.subTest(value=value):
                h=self.handler({'csrf':value});http.handle(h)
                self.assertEqual(h.response['status'],403);self.assert_active()

    def test_missing_or_unexpected_form_field_is_rejected(self):
        for fields in ({},{'other':'x'},{'csrf':self.csrf,'next':'https://example.test'}):
            with self.subTest(fields=tuple(fields)):
                h=self.handler(fields);http.handle(h)
                self.assertEqual(h.response['status'],400);self.assert_active()

    def test_json_or_oversized_form_is_rejected(self):
        for headers in ({'Content-Type':'application/json'},{'Content-Length':'999999'},{'Content-Length':'invalid'}):
            with self.subTest(headers=headers):
                h=self.handler(headers=headers);http.handle(h)
                self.assertEqual(h.response['status'],400);self.assert_active()

    def test_already_closed_session_returns_to_login(self):
        accounts.close_session(self.token)
        h=self.handler();http.handle(h)
        self.assert_redirect_and_cookie_clear(h)

    def test_missing_cookie_returns_to_login(self):
        h=self.handler(cookie=False);http.handle(h)
        self.assert_redirect_and_cookie_clear(h)
        self.assert_active()

    def test_authentication_storage_error_does_not_fake_logout(self):
        h=self.handler()
        with patch.object(accounts,'authenticate_session',side_effect=RuntimeError('unavailable')):
            http.handle(h)
        self.assertEqual(h.response['status'],503)
        self.assertNotIn('Set-Cookie',h.response['headers'])
        self.assertIn('Réessayez',h.response['data'].decode())
        self.assert_active()

    def test_revocation_storage_error_is_html_with_retry_and_keeps_cookie(self):
        h=self.handler()
        with patch.object(accounts,'close_session',side_effect=RuntimeError('unavailable')):
            http.handle(h)
        self.assertEqual(h.response['status'],503)
        self.assertTrue(h.response['ctype'].startswith('text/html'))
        self.assertNotIn('Set-Cookie',h.response['headers'])
        self.assertIn('Votre session n’a pas été fermée',h.response['data'].decode())
        self.assertIn('href="/compte"',h.response['data'].decode())
        self.assert_active()

    def test_json_logout_api_remains_compatible(self):
        h=support.Handler(http.LOGOUT_ROUTE,'POST',payload={},headers={
            'Cookie':f'{http.COOKIE_NAME}={self.token}',
            'X-CheckupAuto-Customer-CSRF':self.csrf,
        })
        http.handle(h)
        self.assertEqual(h.response['status'],200)
        self.assertTrue(h.response['json']['ok'])
        with self.assertRaises(PermissionError):accounts.authenticate_session(self.token)

    def test_dashboard_has_native_form_and_three_accessible_actions(self):
        with patch.object(http,'_google_review_url',return_value='https://g.page/r/test/review'):
            body=http._dashboard_page(self.token,self.account,'test-nonce').decode()
        self.assertIn('action="/compte/deconnexion" method="post"',body)
        self.assertIn('name="csrf" value="'+self.csrf+'"',body)
        self.assertIn('id="logout" class="action-button action-button--logout" type="submit"',body)
        self.assertIn('aria-label="Actions de votre espace client"',body)
        self.assertNotIn("getElementById('logout').addEventListener",body)
        self.assertEqual(body.count('class="action-icon"'),3)
        self.assertIn('/assets/action-controls.css?v=20261008-1',body)


class CustomerActionStylesTest(unittest.TestCase):
    def test_customer_surfaces_share_the_same_local_stylesheet(self):
        root=Path(__file__).parent
        for name in ('index.html','customer_http.py','contact_request.py','app_download.py',
                     'withdrawal_service.py','payment_payline_http.py','booking_page.py',
                     'booking_bridge.py','mobile_claim_delivery.py','admin_server.py'):
            with self.subTest(page=name):
                self.assertIn('/assets/action-controls.css?v=20261008-1',(root/name).read_text())
        css=(root/'assets/action-controls.css').read_text()
        for feature in ('min-height:46px',':focus-visible','[aria-disabled=true]',
                        'prefers-reduced-motion','customer-logout','.report-actions>a'):
            self.assertIn(feature,css)


if __name__=='__main__':
    unittest.main()
