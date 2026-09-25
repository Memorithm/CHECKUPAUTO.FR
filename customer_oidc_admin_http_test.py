import io
import json
import time
import unittest
from unittest.mock import patch

import customer_oidc_admin_http as http


class Handler:
    def __init__(self,path=http.ROUTE,command="GET",payload=None,authorized=True,mfa=True,origin_ok=True):
        self.path=path;self.command=command;self._authorized=authorized;self._mfa=mfa;self._origin=origin_ok
        raw=b"" if payload is None else json.dumps(payload).encode()
        self.rfile=io.BytesIO(raw)
        self.headers={
            "Host":"stage.example",
            "Authorization":"Basic synthetic",
            "Cookie":"mfa=synthetic",
            "Content-Type":"application/json",
            "Content-Length":str(len(raw)),
            "Sec-Fetch-Site":"same-origin",
        }
        self.response=None
    def authorized(self): return self._authorized
    def _mfa_session_valid(self): return self._mfa
    def _admin_origin_ok(self): return self._origin
    def require_auth(self): self.response={"status":401}
    def require_mfa(self): self.response={"status":403,"json":{"error":"two_factor_required"}}
    def send_json(self,obj,status=200,headers=None): self.response={"status":status,"json":obj,"headers":headers or {}}


class CustomerOIDCAdminHttpTest(unittest.TestCase):
    secret="admin-secret"

    def token(self,h):
        return http.csrf_token(self.secret,h.headers,int(time.time()//3600))

    def test_auth_and_mfa_precede_status_access(self):
        h=Handler(authorized=False)
        with patch.object(http.customer_oidc_admin,"status") as status:
            self.assertTrue(http.handle(h,secret=self.secret))
        self.assertEqual(h.response["status"],401);status.assert_not_called()
        h=Handler(mfa=False)
        with patch.object(http.customer_oidc_admin,"status") as status:
            self.assertTrue(http.handle(h,secret=self.secret))
        self.assertEqual(h.response["status"],403);status.assert_not_called()

    def test_get_is_secret_free_and_returns_csrf(self):
        h=Handler()
        data={"providers":[{"id":"google","label":"Google","configured":False,"callbackUrl":"https://stage.example/auth/customer/google/callback"}],"secretsReadable":False}
        with patch.object(http.customer_oidc_admin,"status",return_value=data):
            self.assertTrue(http.handle(h,secret=self.secret))
        self.assertEqual(h.response["status"],200)
        self.assertRegex(h.response["json"]["csrfToken"],r"^[0-9a-f]{64}$")
        self.assertFalse(h.response["json"]["secretsReadable"])
        self.assertNotIn("clientSecret",repr(h.response["json"]))

    def test_save_requires_origin_csrf_and_calls_private_writer(self):
        payload={"action":"save","provider":"google","clientId":"cid","clientSecret":"secret-value"}
        h=Handler(command="POST",payload=payload)
        h.headers["X-CheckupAuto-Customer-OIDC-CSRF"]=self.token(h)
        result={"provider":"google","configured":True,"callbackUrl":"https://stage.example/auth/customer/google/callback","secretsReadable":False}
        with patch.object(http.customer_oidc_admin,"save",return_value=result) as save:
            self.assertTrue(http.handle(h,secret=self.secret))
        self.assertEqual(h.response["status"],201)
        self.assertNotIn("secret-value",repr(h.response))
        save.assert_called_once_with("google","cid","secret-value","https://stage.example")

        bad=Handler(command="POST",payload=payload)
        with patch.object(http.customer_oidc_admin,"save") as save:
            self.assertTrue(http.handle(bad,secret=self.secret))
        self.assertEqual(bad.response["status"],403);save.assert_not_called()

    def test_cross_site_and_duplicate_json_are_refused(self):
        payload={"action":"remove","provider":"google"}
        h=Handler(command="POST",payload=payload,origin_ok=False)
        h.headers["X-CheckupAuto-Customer-OIDC-CSRF"]=self.token(h)
        self.assertTrue(http.handle(h,secret=self.secret))
        self.assertEqual(h.response["status"],403)

        raw=b'{"action":"remove","provider":"google","provider":"apple"}'
        dup=Handler(command="POST",payload={})
        dup.rfile=io.BytesIO(raw);dup.headers["Content-Length"]=str(len(raw));dup.headers["X-CheckupAuto-Customer-OIDC-CSRF"]=self.token(dup)
        self.assertTrue(http.handle(dup,secret=self.secret))
        self.assertEqual(dup.response["status"],400)

    def test_remove_is_explicit_and_secret_free(self):
        payload={"action":"remove","provider":"apple"}
        h=Handler(command="POST",payload=payload)
        h.headers["X-CheckupAuto-Customer-OIDC-CSRF"]=self.token(h)
        result={"provider":"apple","configured":False,"removed":True,"callbackUrl":"https://stage.example/auth/customer/apple/callback","secretsReadable":False}
        with patch.object(http.customer_oidc_admin,"remove",return_value=result) as remove:
            self.assertTrue(http.handle(h,secret=self.secret))
        self.assertEqual(h.response["status"],200);remove.assert_called_once()


if __name__=="__main__":
    unittest.main()
