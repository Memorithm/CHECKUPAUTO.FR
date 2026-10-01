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
        self.operator=True
        self.mfa_valid=True
    def authorized(self): return self.operator
    def require_auth(self): self.send_json({"ok":False,"error":"authentication_required"},401)
    def _mfa_session_valid(self): return self.mfa_valid
    def require_mfa(self): self.send_json({"ok":False,"error":"two_factor_required"},403)
    def _admin_origin_ok(self): return True
    def _read_json(self):
        return json.loads(self.rfile.read(int(self.headers["Content-Length"])))
    def send_json(self,obj,status=200,headers=None):
        self.response={"status":status,"json":obj,"headers":headers or {}}
    def send_bytes(self,data,ctype,status=200,cache="no-store",headers=None):
        self.response={"status":status,"data":data,"ctype":ctype,"headers":headers or {}}


class PaymentTestHttpTest(unittest.TestCase):
    def setUp(self):
        self.mfa=patch.object(http.admin_mfa,"configured",return_value=False)
        self.mfa.start()
        self.addCleanup(self.mfa.stop)

    def test_anonymous_operator_pages_and_actions_are_denied_before_domain_call(self):
        for path in (http.PAGE_ROUTE,http.PROVIDER_ROUTE):
            h=Handler(path);h.operator=False
            with patch.object(http.lab,"enabled",return_value=True):
                self.assertTrue(http.handle(h))
            self.assertEqual(h.response["status"],401)
        actions=(http.SESSION_ROUTE,http.CREATE_ROUTE,http.PREPARE_PAYLINE_ROUTE,http.RESULT_ROUTE,http.STATUS_ROUTE,http.REMOVE_ROUTE)
        methods=("create_session","create_reservation","prepare_payline_checkout","apply_result","status","remove")
        for path,method in zip(actions,methods):
            h=Handler(path,"POST");h.operator=False
            with patch.object(http.lab,"enabled",return_value=True),patch.object(http.lab,method) as operation:
                self.assertTrue(http.handle(h))
            self.assertEqual(h.response["status"],401)
            operation.assert_not_called()

    def test_configured_mfa_is_required_before_issuing_a_test_session(self):
        h=Handler(http.SESSION_ROUTE,"POST");h.mfa_valid=False
        with patch.object(http.lab,"enabled",return_value=True),patch.object(http.admin_mfa,"configured",return_value=True),patch.object(http.lab,"create_session") as create:
            self.assertTrue(http.handle(h))
        self.assertEqual(h.response["status"],403)
        create.assert_not_called()

    def test_operator_with_valid_mfa_can_get_a_test_session(self):
        h=Handler(http.SESSION_ROUTE,"POST")
        with patch.object(http.lab,"enabled",return_value=True),patch.object(http.admin_mfa,"configured",return_value=True),patch.object(http.lab,"create_session",return_value={"ok":True,"token":"operator-test-token"}) as create:
            self.assertTrue(http.handle(h))
        self.assertEqual(h.response["status"],201)
        create.assert_called_once()

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
        body=h.response["data"].decode("utf-8")
        self.assertIn("PAIEMENT SANDBOX UNIQUEMENT",body)
        self.assertIn("Payline homologation réelle",body)

    def test_demo_page_and_status_are_noindex_and_secret_free(self):
        h=Handler(http.DEMO_ROUTE)
        with patch.object(http.lab,"enabled",return_value=True), \
             patch.object(http.lab,"demo_status",return_value={
                 "ok":True,
                 "mode":"staging-demo",
                 "site":{"homepage":"/","booking":"/#reservation","contact":"/contact"},
                 "payment":{
                     "simulation":"/payment/test",
                     "checkout":"/payment/payline/checkout",
                     "paylineSandbox":{
                         "configured":False,"configurationValid":False,
                         "checkoutBound":True,"callbacksBound":True,
                         "livePaymentsEnabled":False,
                         "blockingReasons":["explicit_api_configuration_missing"],
                     },
                 },
                 "backend":{},
                 "refundPolicy":"contact-only",
             }):
            self.assertTrue(http.handle(h))
        self.assertEqual(h.response["status"],200)
        body=h.response["data"].decode("utf-8")
        self.assertIn("DÉMO QUASI-RÉELLE",body)
        self.assertIn("CONFIG API SANDBOX À INSTALLER",body)
        self.assertNotIn("merchantId",body)
        self.assertNotIn("accessKey",body)
        self.assertIn("noindex",h.response["headers"]["X-Robots-Tag"])

        status=Handler(http.DEMO_STATUS_ROUTE)
        with patch.object(http.lab,"enabled",return_value=True), \
             patch.object(http.lab,"demo_status",return_value={
                 "ok":True,"mode":"staging-demo","payment":{"paylineSandbox":{"configured":False}},
             }):
            self.assertTrue(http.handle(status))
        self.assertEqual(status.response["status"],200)
        self.assertFalse(status.response["json"]["payment"]["paylineSandbox"]["configured"])

    def test_prepare_payline_endpoint_returns_first_party_checkout_only(self):
        h=Handler(http.PREPARE_PAYLINE_ROUTE,"POST",{
            "token":"test-token","service":"technical","date":"2026-10-03","time":"09:00",
            "acceptTerms":True,"immediatePerformance":True,
        })
        prepared={
            "ok":True,
            "mode":"reservation-payline-homologation-test",
            "checkoutUrl":"/payment/payline/checkout#ccid=ccid-test&cct=cct-test",
            "paylineSandbox":{"configured":True,"configurationValid":True,"livePaymentsEnabled":False},
        }
        with patch.object(http.lab,"enabled",return_value=True), \
             patch.object(http.lab,"prepare_payline_checkout",return_value=prepared) as prepare:
            self.assertTrue(http.handle(h))
        self.assertEqual(h.response["status"],201)
        self.assertEqual(h.response["json"]["checkoutUrl"],prepared["checkoutUrl"])
        self.assertNotIn("merchantId",repr(h.response["json"]))
        self.assertNotIn("accessKey",repr(h.response["json"]))
        prepare.assert_called_once_with(
            "test-token","technical","2026-10-03","09:00",
            accept_terms=True,immediate_performance=True,
        )

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
