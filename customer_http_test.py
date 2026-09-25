import io
import json
import unittest
from unittest.mock import patch

import customer_http as http


class Handler:
    def __init__(self,path,command="GET",payload=None,headers=None):
        self.path=path
        self.command=command
        raw=json.dumps(payload or {}).encode()
        self.rfile=io.BytesIO(raw)
        self.headers={
            "Content-Type":"application/json",
            "Content-Length":str(len(raw)),
            "Sec-Fetch-Site":"same-origin",
            "Host":"stage.example",
        }
        if headers:self.headers.update(headers)
        self.response=None
        self._csp_nonce=""
        self._headers=[]
        self._status=None
    def _admin_origin_ok(self): return True
    def _request_origin(self): return "https://stage.example"
    def _read_json(self): return json.loads(self.rfile.read(int(self.headers["Content-Length"])))
    def _read_form(self):
        from urllib.parse import parse_qs
        raw=self.rfile.read(int(self.headers["Content-Length"])).decode()
        parsed=parse_qs(raw,keep_blank_values=True)
        return {k:v[0] for k,v in parsed.items()}
    def send_json(self,obj,status=200,headers=None):
        self.response={"status":status,"json":obj,"headers":headers or {}}
    def send_bytes(self,data,ctype,status=200,cache="no-store",headers=None):
        self.response={"status":status,"data":data,"ctype":ctype,"headers":headers or {}}
    def send_redirect(self,location,status=302):
        self.response={"status":status,"location":location}
    def send_response(self,status,message=None):
        self._status=status
    def send_header(self,name,value):
        self._headers.append((name,value))
    def end_headers(self):
        self.response={"status":self._status,"headers":dict(self._headers)}


class CustomerHttpTest(unittest.TestCase):
    def account(self):
        return {
            "ok":True,"accountId":"00000000-0000-4000-8000-000000000001",
            "kind":"individual","displayName":"Client Test","email":"client@example.test",
            "companyName":"","siret":"","providers":["google"],
            "loyalty":{"referralCode":"TEST-1234","currency":"EUR","balanceCents":500,
                       "pendingCents":100,"earnedReferrals":2,"pendingReferrals":1},
            "createdAt":"2026-09-25T00:00:00+00:00","updatedAt":"2026-09-25T00:00:00+00:00",
        }

    def test_login_page_lists_only_provider_status_without_secrets(self):
        h=Handler("/compte")
        with patch.object(http,"_account",return_value=("",None)), \
             patch.object(http.customer_oidc,"provider_status",return_value=[
                 {"id":"google","label":"Google","configured":True},
                 {"id":"apple","label":"Apple","configured":False},
                 {"id":"microsoft","label":"Microsoft / Hotmail","configured":True},
             ]):
            self.assertTrue(http.handle(h))
        body=h.response["data"].decode()
        self.assertEqual(h.response["status"],200)
        self.assertIn("Continuer avec Google",body)
        self.assertIn("Apple · bientôt disponible",body)
        self.assertIn("Microsoft / Hotmail",body)
        self.assertNotIn("clientSecret",body)

    def test_dashboard_uses_csp_nonce_and_server_loyalty_snapshot(self):
        h=Handler("/compte")
        with patch.object(http,"_account",return_value=("session-token",self.account())), \
             patch.object(http.customer_accounts,"csrf_token",return_value="c"*64):
            self.assertTrue(http.handle(h))
        body=h.response["data"].decode()
        self.assertIn("TABLEAU DE BORD CLIENT",body)
        self.assertIn("5.00 €",body)
        self.assertIn("Code TEST-1234",body)
        self.assertIn('nonce="',body)
        self.assertTrue(h._csp_nonce)

    def test_oidc_start_redirects_only_from_configured_begin(self):
        h=Handler("/auth/customer/google")
        with patch.object(http.customer_oidc,"begin",return_value="https://accounts.example/auth?state=x") as begin:
            self.assertTrue(http.handle(h))
        self.assertEqual(h.response["status"],302)
        self.assertEqual(h.response["location"],"https://accounts.example/auth?state=x")
        begin.assert_called_once_with("google","https://stage.example")

    def test_oidc_callback_sets_secure_httponly_session_cookie(self):
        h=Handler("/auth/customer/google/callback?state=s&code=c")
        with patch.object(http.customer_oidc,"complete",return_value={
            "account":self.account(),
            "session":{"token":"opaque-session-token","maxAge":43200},
        }):
            self.assertTrue(http.handle(h))
        self.assertEqual(h.response["status"],303)
        cookie=h.response["headers"]["Set-Cookie"]
        self.assertIn("HttpOnly",cookie)
        self.assertIn("Secure",cookie)
        self.assertIn("SameSite=Lax",cookie)
        self.assertNotIn("client@example.test",cookie)

    def test_profile_mutation_requires_same_origin_session_and_csrf(self):
        h=Handler("/api/customer/profile","POST",{
            "kind":"professional","displayName":"Client Test",
            "companyName":"Garage Exemple","siret":"12345678901234",
        },headers={"Cookie":"checkupauto_customer=token","X-CheckupAuto-Customer-CSRF":"c"*64})
        with patch.object(http,"_account",return_value=("token",self.account())), \
             patch.object(http.customer_accounts,"verify_csrf",return_value=True), \
             patch.object(http.customer_accounts,"update_profile",return_value={**self.account(),"kind":"professional"}) as update:
            self.assertTrue(http.handle(h))
        self.assertEqual(h.response["status"],200)
        self.assertEqual(h.response["json"]["kind"],"professional")
        update.assert_called_once()

        bad=Handler("/api/customer/profile","POST",{
            "kind":"individual","displayName":"Client Test","companyName":"","siret":"",
        },headers={"Cookie":"checkupauto_customer=token","X-CheckupAuto-Customer-CSRF":"bad"})
        with patch.object(http,"_account",return_value=("token",self.account())), \
             patch.object(http.customer_accounts,"verify_csrf",return_value=False):
            self.assertTrue(http.handle(bad))
        self.assertEqual(bad.response["status"],403)

    def test_cross_site_profile_post_is_rejected(self):
        h=Handler("/api/customer/profile","POST",{
            "kind":"individual","displayName":"Client Test","companyName":"","siret":"",
        },headers={"Sec-Fetch-Site":"cross-site","Cookie":"checkupauto_customer=token",
                   "X-CheckupAuto-Customer-CSRF":"c"*64})
        with patch.object(http,"_account",return_value=("token",self.account())):
            self.assertTrue(http.handle(h))
        self.assertEqual(h.response["status"],403)


if __name__=="__main__":
    unittest.main()
