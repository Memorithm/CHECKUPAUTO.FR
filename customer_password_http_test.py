import io
import json
import unittest
from urllib.parse import urlencode
from unittest.mock import patch

import customer_http as http


class Handler:
    def __init__(self,path,command="GET",payload=None,headers=None):
        self.path=path
        self.command=command
        raw=json.dumps(payload or {}).encode()
        self.rfile=io.BytesIO(raw)
        self.headers={"Content-Type":"application/json","Content-Length":str(len(raw)),"Sec-Fetch-Site":"same-origin","Host":"stage.example"}
        if headers:self.headers.update(headers)
        self.response=None; self._headers=[]; self._status=None; self._csp_nonce=""
    def _admin_origin_ok(self): return True
    def _read_json(self): return json.loads(self.rfile.read(int(self.headers["Content-Length"])))
    def _read_form(self):
        from urllib.parse import parse_qs
        parsed=parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode(),keep_blank_values=True)
        return {k:v[0] for k,v in parsed.items()}
    def send_json(self,obj,status=200,headers=None): self.response={"status":status,"json":obj,"headers":headers or {}}
    def send_bytes(self,data,ctype,status=200,cache="no-store",headers=None): self.response={"status":status,"data":data,"ctype":ctype,"headers":headers or {}}
    def send_redirect(self,location,status=302): self.response={"status":status,"location":location}
    def send_response(self,status,message=None): self._status=status
    def send_header(self,name,value): self._headers.append((name,value))
    def end_headers(self): self.response={"status":self._status,"headers":dict(self._headers),"cookies":[v for k,v in self._headers if k=="Set-Cookie"]}


def form_handler(path,payload,headers=None):
    raw=urlencode(payload).encode()
    merged={"Content-Type":"application/x-www-form-urlencoded","Content-Length":str(len(raw))}
    if headers: merged.update(headers)
    h=Handler(path,"POST",headers=merged); h.rfile=io.BytesIO(raw); return h


class CustomerPasswordHttpTest(unittest.TestCase):
    def account(self):
        return {"accountId":"00000000-0000-4000-8000-000000000001","displayName":"Client Test","email":"client@example.test"}

    def test_login_page_exposes_email_login_registration_and_recovery(self):
        body=http._login_page().decode()
        self.assertIn("Se connecter par e-mail",body)
        self.assertIn("Créer un compte par e-mail",body)
        self.assertIn("Mot de passe oublié",body)
        self.assertIn('autocomplete="current-password"',body)
        self.assertIn('autocomplete="new-password"',body)

    def test_registration_sends_verification_link(self):
        target="/compte/reserver?returnTo=%2Fgo%2Fbooking%3Fservice%3DContr%25C3%25B4le%2Btechnique%26preferredDate%3D2026-10-08%26preferredTime%3D10%253A30"
        password="A long customer passphrase 42"
        h=form_handler("/compte/inscription",{"displayName":"Client Test","email":"client@example.test","password":password,"passwordConfirm":password,"returnTo":target})
        pending={"email":"client@example.test","token":"v"*43,"purpose":"verify"}
        with patch.object(http.email_gateway,"configured",return_value=True), patch.object(http.customer_password_auth,"begin_registration",return_value=pending) as begin, patch.object(http.email_gateway,"send_email",return_value={"ok":True}) as send:
            self.assertTrue(http.handle(h))
        self.assertEqual(h.response["status"],200)
        begin.assert_called_once_with("client@example.test","Client Test",password)
        self.assertIn("/compte/verifier-email?",send.call_args.args[2])
        self.assertNotIn(password,h.response["data"].decode())

    def test_login_sets_secure_cookie_and_preserves_target(self):
        target="/compte/reserver?returnTo=%2Fgo%2Fbooking%3Fservice%3DContr%25C3%25B4le%2Btechnique%26preferredDate%3D2026-10-08%26preferredTime%3D10%253A30"
        password="A long customer passphrase 42"
        h=form_handler("/compte/connexion",{"email":"client@example.test","password":password,"returnTo":target})
        session={"token":"s"*48,"maxAge":43200,"accountId":self.account()["accountId"]}
        with patch.object(http.customer_password_auth,"authenticate",return_value=self.account()), patch.object(http.customer_accounts,"issue_session",return_value=session):
            self.assertTrue(http.handle(h))
        self.assertEqual(h.response["status"],303)
        self.assertEqual(h.response["headers"]["Location"],target)
        cookie=h.response["cookies"][0]
        self.assertIn("HttpOnly",cookie); self.assertIn("Secure",cookie); self.assertIn("SameSite=Lax",cookie)

    def test_verification_consumes_token_and_opens_session(self):
        account=self.account(); session={"token":"s"*48,"maxAge":43200,"accountId":account["accountId"]}
        h=Handler("/compte/verifier-email?token="+("v"*43))
        with patch.object(http.customer_password_auth,"verify_registration",return_value=account) as verify, patch.object(http.customer_accounts,"issue_session",return_value=session):
            self.assertTrue(http.handle(h))
        self.assertEqual(h.response["status"],303)
        self.assertEqual(h.response["headers"]["Location"],"/compte")
        verify.assert_called_once_with("v"*43)

    def test_reset_request_is_enumeration_safe(self):
        h=form_handler("/compte/mot-de-passe-oublie",{"email":"unknown@example.test","returnTo":""})
        with patch.object(http.email_gateway,"configured",return_value=True), patch.object(http.customer_password_auth,"begin_reset",return_value={"ok":True,"deliver":False}), patch.object(http.email_gateway,"send_email") as send:
            self.assertTrue(http.handle(h))
        self.assertEqual(h.response["status"],200)
        self.assertIn("Si un compte par e-mail correspond",h.response["data"].decode())
        send.assert_not_called()

    def test_cross_site_login_is_rejected(self):
        h=form_handler("/compte/connexion",{"email":"client@example.test","password":"A long customer passphrase 42","returnTo":""},{"Sec-Fetch-Site":"cross-site"})
        with patch.object(http.customer_password_auth,"authenticate") as authenticate:
            self.assertTrue(http.handle(h))
        self.assertEqual(h.response["status"],403)
        authenticate.assert_not_called()


if __name__=="__main__": unittest.main()
