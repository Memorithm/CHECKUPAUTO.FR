import io
import json
import re
import shutil
import subprocess
import tempfile
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
        self.response={"status":self._status,"headers":dict(self._headers),"cookies":[v for k,v in self._headers if k=="Set-Cookie"]}


class CustomerHttpTest(unittest.TestCase):
    def account(self):
        return {
            "ok":True,"accountId":"00000000-0000-4000-8000-000000000001",
            "kind":"individual","displayName":"Client Test","email":"client@example.test",
            "companyName":"","siret":"","phone":"0612345678",
            "addressLine1":"12 rue de Paris","addressLine2":"",
            "postalCode":"78130","city":"Les Mureaux","contactDetailsComplete":True,
            "providers":["google"],
            "loyalty":{"referralCode":"TEST-1234","currency":"EUR","balanceCents":500,
                       "pendingCents":100,"earnedReferrals":2,"pendingReferrals":1},
            "createdAt":"2026-09-25T00:00:00+00:00","updatedAt":"2026-09-25T00:00:00+00:00",
        }

    def test_login_page_lists_only_active_public_providers_without_secrets(self):
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
        self.assertNotIn("Microsoft / Hotmail",body)
        self.assertNotIn("clientSecret",body)

    def test_public_provider_api_omits_retired_microsoft_provider(self):
        h=Handler("/api/customer/providers")
        with patch.object(http.customer_oidc,"provider_status",return_value=[
            {"id":"google","label":"Google","configured":True},
            {"id":"apple","label":"Apple","configured":False},
            {"id":"microsoft","label":"Microsoft / Hotmail","configured":True},
        ]):
            self.assertTrue(http.handle(h))
        self.assertEqual([row["id"] for row in h.response["json"]["providers"]],["google","apple"])

    def test_retired_microsoft_customer_auth_route_is_not_public(self):
        h=Handler("/auth/customer/microsoft")
        with patch.object(http.customer_oidc,"begin") as begin:
            self.assertFalse(http.handle(h))
        self.assertIsNone(h.response)
        begin.assert_not_called()

    def test_dashboard_uses_csp_nonce_and_server_loyalty_snapshot(self):
        h=Handler("/compte")
        with patch.object(http,"_account",return_value=("session-token",self.account())), \
             patch.object(http.customer_accounts,"csrf_token",return_value="c"*64):
            self.assertTrue(http.handle(h))
        body=h.response["data"].decode()
        self.assertIn("TABLEAU DE BORD CLIENT",body)
        self.assertIn("5.00 €",body)
        self.assertIn("Code TEST-1234",body)
        self.assertIn("Rattacher à l’app iOS",body)
        self.assertIn('id="ct-report"',body)
        self.assertIn('href="/compte/reserver">Réserver un contrôle',body)
        self.assertIn('Consulter mes rendez-vous Mercure',body)
        self.assertNotIn('Réserver ou consulter mes rendez-vous sur le planning actuel',body)
        self.assertIn('nonce="',body)
        self.assertTrue(h._csp_nonce)

    @unittest.skipUnless(shutil.which("node"),"Node.js is required for inline dashboard syntax validation")
    def test_dashboard_inline_javascript_parses(self):
        h=Handler("/compte")
        with patch.object(http,"_account",return_value=("session-token",self.account())), \
             patch.object(http.customer_accounts,"csrf_token",return_value="c"*64):
            self.assertTrue(http.handle(h))
        body=h.response["data"].decode()
        match=re.search(r'<script nonce="[^"]+">(.*?)</script>',body,re.S)
        self.assertIsNotNone(match)
        with tempfile.NamedTemporaryFile("w",suffix=".js",delete=False) as tmp:
            tmp.write(match.group(1))
            path=tmp.name
        try:
            result=subprocess.run(["node","--check",path],capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
        finally:
            import os
            os.unlink(path)

    def test_oidc_start_redirects_only_from_configured_begin(self):
        h=Handler("/auth/customer/google")
        with patch.object(http.customer_oidc,"begin",return_value="https://accounts.example/auth?state=sssssssssssssssssssssssssssssssssssssssssss") as begin:
            self.assertTrue(http.handle(h))
        self.assertEqual(h.response["status"],302)
        self.assertEqual(h.response["headers"]["Location"],"https://accounts.example/auth?state=sssssssssssssssssssssssssssssssssssssssssss")
        binding=h.response["cookies"][0].split("=",1)[1].split(";",1)[0]
        begin.assert_called_once_with("google","https://stage.example",browser_binding=binding,mobile=False)
        self.assertIn("__Host-checkupauto_oidc_google_sssssssssssssssssssssssssssssssssssssssssss=",h.response["cookies"][0])
        self.assertIn("HttpOnly; Secure; SameSite=Lax",h.response["cookies"][0])

    def test_oidc_callback_sets_secure_httponly_session_cookie(self):
        h=Handler("/auth/customer/google/callback?state=sssssssssssssssssssssssssssssssssssssssssss&code=c",headers={"Cookie":"__Host-checkupauto_oidc_google_sssssssssssssssssssssssssssssssssssssssssss="+"b"*43})
        with patch.object(http.customer_oidc,"complete",return_value={
            "account":self.account(),
            "session":{"token":"opaque-session-token","maxAge":43200},
        }) as complete:
            self.assertTrue(http.handle(h))
        complete.assert_called_once_with("google","sssssssssssssssssssssssssssssssssssssssssss","c",browser_binding="b"*43,origin="https://stage.example")
        self.assertEqual(h.response["status"],303)
        cookie=h.response["cookies"][0]
        self.assertIn("HttpOnly",cookie)
        self.assertIn("Secure",cookie)
        self.assertIn("SameSite=Lax",cookie)
        self.assertNotIn("client@example.test",cookie)

    def test_apple_flow_cookie_supports_cross_site_form_post(self):
        h=Handler("/auth/customer/apple")
        with patch.object(http.customer_oidc,"begin",return_value="https://appleid.apple.com/auth/authorize?state=sssssssssssssssssssssssssssssssssssssssssss"):
            http.handle(h)
        self.assertIn("__Host-checkupauto_oidc_apple_sssssssssssssssssssssssssssssssssssssssssss=",h.response["cookies"][0])
        self.assertIn("HttpOnly; Secure; SameSite=None",h.response["cookies"][0])

    def test_callback_rejects_duplicate_state_and_clears_flow_cookie(self):
        h=Handler("/auth/customer/google/callback?state=a&state=b&code=c")
        with patch.object(http.customer_oidc,"complete") as complete:
            http.handle(h)
        self.assertEqual(h.response["status"],400)
        complete.assert_not_called()
        self.assertNotIn("Set-Cookie",h.response["headers"])

    def test_apple_post_rejects_duplicate_state_before_token_exchange(self):
        raw=b'state=a&state=b&code=c'
        h=Handler("/auth/customer/apple/callback","POST",headers={
            "Content-Type":"application/x-www-form-urlencoded","Content-Length":str(len(raw))})
        h.rfile=io.BytesIO(raw)
        with patch.object(http.customer_oidc,"complete") as complete:
            http.handle(h)
        self.assertEqual(h.response["status"],400)
        complete.assert_not_called()

    def test_concurrent_provider_flows_use_distinct_cookies_and_clear_only_their_own(self):
        states=("a"*43,"b"*43)
        cookies=[]
        for state in states:
            h=Handler("/auth/customer/google")
            with patch.object(http.customer_oidc,"begin",return_value="https://accounts.example/auth?state="+state):
                http.handle(h)
            cookies.append(h.response["cookies"][0].split(";",1)[0])
        self.assertNotEqual(cookies[0].split("=",1)[0],cookies[1].split("=",1)[0])
        h=Handler("/auth/customer/google/callback?state="+states[0]+"&code=bad",headers={"Cookie":"; ".join(cookies)})
        with patch.object(http.customer_oidc,"complete",side_effect=http.customer_oidc.CustomerOIDCError("failed")):
            http.handle(h)
        cleared=h.response["headers"]["Set-Cookie"]
        self.assertTrue(cleared.startswith(cookies[0].split("=",1)[0]+"="))
        self.assertNotIn(states[1],cleared)

    def test_profile_mutation_requires_same_origin_session_and_csrf(self):
        h=Handler("/api/customer/profile","POST",{
            "kind":"professional","displayName":"Client Test",
            "companyName":"Garage Exemple","siret":"12345678901234",
            "phone":"0612345678","addressLine1":"12 rue de Paris",
            "addressLine2":"","postalCode":"78130","city":"Les Mureaux",
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

    def test_booking_from_customer_space_requires_contact_confirmation_page(self):
        h=Handler("/compte/reserver",headers={"Cookie":"checkupauto_customer=token"})
        passage={
            "passageToken":"p"*43,
            "expiresAt":"2026-10-05T12:00:00+00:00",
            "contactDetailsComplete":True,
        }
        with patch.object(http,"_account",return_value=("token",self.account())), \
             patch.object(http.customer_accounts,"begin_passage_confirmation",return_value=passage) as begin, \
             patch.object(http.customer_accounts,"profile",return_value=self.account()), \
             patch.object(http.customer_accounts,"csrf_token",return_value="c"*64):
            self.assertTrue(http.handle(h))
        body=h.response["data"].decode()
        self.assertEqual(h.response["status"],200)
        self.assertIn("Vos coordonnées sont-elles toujours à jour",body)
        self.assertIn("0612345678",body)
        self.assertIn("12 rue de Paris",body)
        self.assertIn("Oui, elles sont à jour",body)
        self.assertIn("Modifier",body)
        begin.assert_called_once_with(self.account()["accountId"])

    def test_confirmed_legacy_passage_is_validated_but_not_consumed_before_reservation(self):
        token="p"*43
        h=Handler("/compte/reserver?passage="+token,headers={"Cookie":"checkupauto_customer=token"})
        with patch.object(http,"_account",return_value=("token",self.account())), \
             patch.object(http.customer_accounts,"validate_passage_confirmation",return_value={"ok":True}) as validate:
            self.assertTrue(http.handle(h))
        self.assertEqual(h.response["status"],303)
        self.assertEqual(h.response["location"],"/#reservation")
        validate.assert_called_once_with(self.account()["accountId"],token)

    def test_current_contact_confirmation_requires_csrf_and_returns_one_time_continue_url(self):
        passage="p"*43
        h=Handler("/api/customer/passage/confirm","POST",{
            "passageToken":passage,
            "action":"validated",
        },headers={
            "Cookie":"checkupauto_customer=token",
            "X-CheckupAuto-Customer-CSRF":"c"*64,
        })
        with patch.object(http,"_account",return_value=("token",self.account())), \
             patch.object(http.customer_accounts,"verify_csrf",return_value=True), \
             patch.object(http.customer_accounts,"confirm_passage_contact",return_value={"confirmed":True}) as confirm:
            self.assertTrue(http.handle(h))
        self.assertEqual(h.response["status"],200)
        self.assertTrue(h.response["json"]["confirmed"])
        self.assertEqual(h.response["json"]["continueUrl"],"/#reservation")
        confirm.assert_called_once_with(self.account()["accountId"],passage,action="validated")

    def test_contact_confirmation_can_resume_the_selected_booking_handoff(self):
        passage="p"*43
        return_to="/go/booking?service=Contr%C3%B4le+technique&preferredDate=2026-10-08&preferredTime=10%3A30"
        h=Handler("/api/customer/passage/confirm","POST",{
            "passageToken":passage,
            "returnTo":return_to,
            "action":"validated",
        },headers={
            "Cookie":"checkupauto_customer=token",
            "X-CheckupAuto-Customer-CSRF":"c"*64,
        })
        with patch.object(http,"_account",return_value=("token",self.account())), \
             patch.object(http.customer_accounts,"verify_csrf",return_value=True), \
             patch.object(http.customer_accounts,"confirm_passage_contact",return_value={"confirmed":True}):
            self.assertTrue(http.handle(h))
        self.assertEqual(h.response["status"],200)
        self.assertEqual(h.response["json"]["continueUrl"],return_to)

    def test_booking_confirmation_redirect_rejects_external_return_target(self):
        safe=http.booking_confirmation_url("/go/booking?service=Contr%C3%B4le+technique")
        self.assertTrue(safe.startswith("/compte/reserver?returnTo="))
        self.assertEqual(http.booking_confirmation_url("https://evil.example/go/booking"),"/compte/reserver")

    def test_authenticated_booking_consumes_latest_confirmation_only_at_handoff(self):
        h=Handler("/go/booking",headers={"Cookie":"checkupauto_customer=token"})
        with patch.object(http,"_account",return_value=("token",self.account())), \
             patch.object(http.customer_accounts,"consume_latest_passage_confirmation",return_value={
                 "consumed":True,"confirmedAt":"2026-10-05T12:00:00+00:00"
             }) as consume:
            result=http.consume_booking_confirmation(h)
        self.assertTrue(result["required"])
        self.assertTrue(result["consumed"])
        consume.assert_called_once_with(self.account()["accountId"])

    def test_modified_contact_confirmation_updates_profile_before_confirmation(self):
        passage="p"*43
        payload={
            "passageToken":passage,"action":"modified",
            "phone":"0699999999","addressLine1":"20 avenue du Centre",
            "addressLine2":"Bâtiment A","postalCode":"78130","city":"Les Mureaux",
        }
        h=Handler("/api/customer/passage/confirm","POST",payload,headers={
            "Cookie":"checkupauto_customer=token",
            "X-CheckupAuto-Customer-CSRF":"c"*64,
        })
        with patch.object(http,"_account",return_value=("token",self.account())), \
             patch.object(http.customer_accounts,"verify_csrf",return_value=True), \
             patch.object(http.customer_accounts,"update_contact_details",return_value=self.account()) as update, \
             patch.object(http.customer_accounts,"confirm_passage_contact",return_value={"confirmed":True}) as confirm:
            self.assertTrue(http.handle(h))
        self.assertEqual(h.response["status"],200)
        update.assert_called_once_with(
            self.account()["accountId"],
            phone="0699999999",
            address_line1="20 avenue du Centre",
            address_line2="Bâtiment A",
            postal_code="78130",
            city="Les Mureaux",
        )
        confirm.assert_called_once_with(self.account()["accountId"],passage,action="modified")

    def test_wallet_mobile_claim_is_session_csrf_bound_and_returns_one_time_app_link(self):
        h=Handler("/api/customer/wallet/mobile-claim","POST",{},headers={
            "Cookie":"checkupauto_customer=token",
            "X-CheckupAuto-Customer-CSRF":"c"*64,
        })
        issued={
            "claimToken":"rw_"+"x"*43,
            "claimType":"referral_wallet",
            "expiresAt":"2026-09-25T22:00:00+00:00",
            "rawTokenPersisted":False,
        }
        with patch.object(http,"_account",return_value=("token",self.account())), \
             patch.object(http.customer_accounts,"verify_csrf",return_value=True), \
             patch.object(http.referral_wallet_claims,"issue",return_value=issued) as issue:
            self.assertTrue(http.handle(h))
        self.assertEqual(h.response["status"],201)
        self.assertEqual(h.response["json"]["claimType"],"referral_wallet")
        self.assertTrue(h.response["json"]["claimUrl"].startswith("https://stage.example/app/claim#token=rw_"))
        self.assertFalse(h.response["json"]["rawTokenPersisted"])
        self.assertNotIn("accountId",repr(h.response["json"]))
        issue.assert_called_once_with("TEST-1234")

        bad=Handler("/api/customer/wallet/mobile-claim","POST",{},headers={
            "Cookie":"checkupauto_customer=token",
            "X-CheckupAuto-Customer-CSRF":"bad",
        })
        with patch.object(http,"_account",return_value=("token",self.account())), \
             patch.object(http.customer_accounts,"verify_csrf",return_value=False), \
             patch.object(http.referral_wallet_claims,"issue") as issue:
            self.assertTrue(http.handle(bad))
        self.assertEqual(bad.response["status"],403)
        issue.assert_not_called()

    def test_report_list_requires_customer_session(self):
        h=Handler("/api/customer/reports")
        with patch.object(http,"_account",return_value=("",None)):
            self.assertTrue(http.handle(h))
        self.assertEqual(h.response["status"],401)

    def test_report_upload_is_csrf_bound_and_passes_raw_bytes_only_to_private_pipeline(self):
        raw=b"synthetic-jpeg-bytes"
        h=Handler("/api/customer/reports","POST",headers={
            "Cookie":"checkupauto_customer=token",
            "X-CheckupAuto-Customer-CSRF":"c"*64,
            "Content-Type":"image/jpeg",
            "Content-Length":str(len(raw)),
            "X-CheckupAuto-Filename":"controle%20technique.jpg",
        })
        h.rfile=io.BytesIO(raw)
        created={"reportId":"00000000-0000-4000-8000-000000000010","rawDocumentRetained":False}
        with patch.object(http,"_account",return_value=("token",self.account())), \
             patch.object(http.customer_accounts,"verify_csrf",return_value=True), \
             patch.object(http.customer_ct_reports,"ingest",return_value=created) as ingest:
            self.assertTrue(http.handle(h))
        self.assertEqual(h.response["status"],201)
        self.assertFalse(h.response["json"]["rawDocumentRetained"])
        ingest.assert_called_once_with(
            self.account()["accountId"],"controle technique.jpg","image/jpeg",raw
        )

    def test_report_markdown_download_is_account_scoped(self):
        report_id="00000000-0000-4000-8000-000000000010"
        h=Handler("/api/customer/reports/"+report_id+"?format=md",headers={
            "Cookie":"checkupauto_customer=token",
        })
        report={
            "reportId":report_id,
            "markdown":"# Rapport\n\nConseil",
        }
        with patch.object(http,"_account",return_value=("token",self.account())), \
             patch.object(http.customer_ct_reports,"get_report",return_value=report) as get_report:
            self.assertTrue(http.handle(h))
        self.assertEqual(h.response["status"],200)
        self.assertEqual(h.response["ctype"],"text/markdown; charset=utf-8")
        self.assertIn("attachment;",h.response["headers"]["Content-Disposition"])
        get_report.assert_called_once_with(self.account()["accountId"],report_id)

    def test_report_delete_requires_csrf_and_uses_authenticated_account(self):
        report_id="00000000-0000-4000-8000-000000000010"
        h=Handler("/api/customer/reports/delete","POST",{"reportId":report_id},headers={
            "Cookie":"checkupauto_customer=token",
            "X-CheckupAuto-Customer-CSRF":"c"*64,
        })
        with patch.object(http,"_account",return_value=("token",self.account())), \
             patch.object(http.customer_accounts,"verify_csrf",return_value=True), \
             patch.object(http.customer_ct_reports,"delete_report",return_value=True) as delete:
            self.assertTrue(http.handle(h))
        self.assertEqual(h.response["status"],200)
        self.assertTrue(h.response["json"]["removed"])
        delete.assert_called_once_with(self.account()["accountId"],report_id)

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

