import io
import json
import unittest
from unittest.mock import patch

import payment_test_http as http


class Handler:
    def __init__(self,path,command="GET",payload=None):
        self.path=path
        self.command=command
        raw=json.dumps(payload or {}).encode()
        self.rfile=io.BytesIO(raw)
        self.headers={
            "Content-Type":"application/json",
            "Content-Length":str(len(raw)),
            "Sec-Fetch-Site":"same-origin",
        }
        self.response=None
        self._csp_nonce=""
    def _admin_origin_ok(self): return True
    def _read_json(self):
        return json.loads(self.rfile.read(int(self.headers["Content-Length"])))
    def send_json(self,obj,status=200,headers=None):
        self.response={"status":status,"json":obj,"headers":headers or {}}
    def send_bytes(self,data,ctype,status=200,cache="no-store",headers=None):
        self.response={"status":status,"data":data,"ctype":ctype,"headers":headers or {}}


class PaymentTestHttpTest(unittest.TestCase):
    def test_pages_are_hidden_when_test_mode_disabled(self):
        h=Handler(http.PAGE_ROUTE)
        with patch.object(http.lab,"enabled",return_value=False):
            self.assertTrue(http.handle(h))
        self.assertEqual(h.response["status"],404)

    def test_test_page_is_noindex_and_explicitly_no_debit(self):
        h=Handler(http.PAGE_ROUTE)
        with patch.object(http.lab,"enabled",return_value=True):
            self.assertTrue(http.handle(h))
        self.assertEqual(h.response["status"],200)
        self.assertIn("noindex",h.response["headers"]["X-Robots-Tag"])
        self.assertIn("AUCUN D",h.response["data"].decode("utf-8"))

    def test_session_endpoint_returns_only_test_session_data(self):
        h=Handler(http.SESSION_ROUTE,"POST",{})
        with patch.object(http.lab,"enabled",return_value=True), \
             patch.object(http.lab,"create_session",return_value={
                 "ok":True,"mode":"reservation-payment-test","token":"test-token",
                 "expiresAt":"2026-09-24T20:00:00+00:00",
                 "safety":"no bank debit",
             }):
            self.assertTrue(http.handle(h))
        self.assertEqual(h.response["status"],201)
        self.assertEqual(h.response["json"]["token"],"test-token")
        self.assertNotIn("merchantId",repr(h.response["json"]))
        self.assertNotIn("accessKey",repr(h.response["json"]))

    def test_cross_site_post_is_rejected_before_domain_call(self):
        h=Handler(http.SESSION_ROUTE,"POST",{})
        h.headers["Sec-Fetch-Site"]="cross-site"
        with patch.object(http.lab,"enabled",return_value=True), \
             patch.object(http.lab,"create_session") as create:
            self.assertTrue(http.handle(h))
        self.assertEqual(h.response["status"],403)
        create.assert_not_called()


if __name__=="__main__":
    unittest.main()
