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
        self.assertIn("Se connecter par e-mail",body)
        self.assertIn("Créer un compte par e-mail",body)
        self.assertIn("Mot de passe oublié",body)
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

    def test_contact_intent_explains_customer_account_requirement(self):
        h=Handler("/compte?intent=contact")
        with patch.object(http,"_account",return_value=("",None)):
            self.assertTrue(http.handle(h))
        body=h.response["data"].decode()
        self.assertEqual(h.response["status"],200)
        self.assertIn("Pour nous contacter, connectez-vous ou créez votre compte client",body)
        self.assertIn("par e-mail, Google ou Apple",body)
        self.assertIn("sécuriser et d’identifier les échanges",body)
        self.assertIn('class="providers"',body)

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
        self.assertIn('href="/#reservation">Réserver un contrôle',body)
        self.assertIn('href="#mes-vehicules">Mes véhicules',body)
        self.assertIn('href="/contact">Nous contacter',body)
        self.assertIn('href="/contact?intent=suggestion">Faire une suggestion',body)
        self.assertIn("Donner mon avis sur Google",body)
        self.assertIn("search.google.com/local/writereview?placeid=ChIJZ82oNlGS5kcRj99QzDs2Fwo",body)
        self.assertIn("Les avis ne sont ni filtrés ni liés à une récompense",body)
        self.assertIn("PROFIL ET COORDONNÉES",body)
        self.assertIn("E-mail vérifié",body)
        self.assertIn("Téléphone",body)
        self.assertIn("Adresse",body)
        self.assertIn("Code postal",body)
        self.assertIn("Ville",body)
        self.assertIn('Consulter mes rendez-vous Mercure',body)
        self.assertNotIn('Réserver ou consulter mes rendez-vous sur le planning actuel',body)
        self.assertIn('nonce="',body)
        self.assertTrue(h._csp_nonce)

    def test_dashboard_exposes_mes_vehicules_section_and_existing_vehicle(self):
        account=self.account()
        account["vehicles"]=[{
            "vehicleId":"11111111-1111-4111-8111-111111111111",
            "registrationSystem":"siv","registration":"AA-123-AA",
            "formulaNumberPresent":True,"cardIssueDate":"","updatedAt":"2026-10-07T00:00:00+00:00",
        }]
        h=Handler("/compte")
        with patch.object(http,"_account",return_value=("session-token",account)), \
             patch.object(http.customer_accounts,"csrf_token",return_value="c"*64):
            self.assertTrue(http.handle(h))
        body=h.response["data"].decode()
        self.assertIn("MES VÉHICULES",body)
        self.assertIn("Vos véhicules enregistrés",body)
        self.assertIn('id="vehicleList"',body)
        self.assertIn('id="vehicleForm"',body)
        self.assertIn("AA-123-AA",body)
        self.assertIn("Numéro de formule",body)
        self.assertIn("Réserver un contrôle",body)

    def test_customer_vehicle_api_lists_saves_and_deletes_account_scoped_vehicles(self):
        vehicle={
            "vehicleId":"11111111-1111-4111-8111-111111111111",
            "registrationSystem":"siv","registration":"AA-123-AA",
            "formulaNumberPresent":True,"cardIssueDate":"","updatedAt":"2026-10-07T00:00:00+00:00",
        }
        listing=Handler("/api/customer/vehicles")
        with patch.object(http,"_account",return_value=("token",self.account())), \
             patch.object(http.customer_accounts,"list_vehicles",return_value=[vehicle]) as list_vehicles:
            self.assertTrue(http.handle(listing))
        self.assertEqual(listing.response["status"],200)
        self.assertEqual(listing.response["json"]["vehicles"],[vehicle])
        list_vehicles.assert_called_once_with(self.account()["accountId"])

        payload={
            "vehicleId":"","registrationSystem":"siv","registration":"aa 123 aa",
            "formulaNumber":"AB12CD34EF5","cardIssueDate":"",
        }
        saving=Handler("/api/customer/vehicles","POST",payload,headers={"X-CheckupAuto-Customer-CSRF":"c"*64})
        with patch.object(http,"_account",return_value=("token",self.account())), \
             patch.object(http.customer_accounts,"verify_csrf",return_value=True), \
             patch.object(http.customer_accounts,"save_vehicle",return_value=vehicle) as save, \
             patch.object(http.customer_accounts,"list_vehicles",return_value=[vehicle]):
            self.assertTrue(http.handle(saving))
        self.assertEqual(saving.response["status"],201)
        self.assertTrue(saving.response["json"]["ok"])
        save.assert_called_once_with(
            self.account()["accountId"],vehicle_id="",registration_system="siv",
            registration="aa 123 aa",formula_number="AB12CD34EF5",card_issue_date="",
        )

        deleting=Handler("/api/customer/vehicles/delete","POST",{"vehicleId":vehicle["vehicleId"]},headers={"X-CheckupAuto-Customer-CSRF":"c"*64})
        with patch.object(http,"_account",return_value=("token",self.account())), \
             patch.object(http.customer_accounts,"verify_csrf",return_value=True), \
             patch.object(http.customer_accounts,"delete_vehicle",return_value=vehicle) as delete, \
             patch.object(http.customer_accounts,"list_vehicles",return_value=[]):
            self.assertTrue(http.handle(deleting))
        self.assertEqual(deleting.response["status"],200)
        self.assertEqual(deleting.response["json"]["vehicles"],[])
        delete.assert_called_once_with(self.account()["accountId"],vehicle["vehicleId"])

    def test_customer_vehicle_mutations_require_csrf(self):
        h=Handler("/api/customer/vehicles","POST",{
            "vehicleId":"","registrationSystem":"siv","registration":"AA-123-AA",
            "formulaNumber":"AB12CD34EF5","cardIssueDate":"",
        })
        with patch.object(http,"_account",return_value=("token",self.account())), \
             patch.object(http.customer_accounts,"verify_csrf",return_value=False), \
             patch.object(http.customer_accounts,"save_vehicle") as save:
            self.assertTrue(http.handle(h))
        self.assertEqual(h.response["status"],403)
        save.assert_not_called()

    def test_google_review_url_uses_valid_configured_google_host(self):
        with patch.object(http.site_config_store,"load",return_value={
            "business":{"googleReviewUrl":"https://g.page/r/example/review"}
        }):
            self.assertEqual(http._google_review_url(),"https://g.page/r/example/review")
        with patch.object(http.site_config_store,"load",return_value={
            "business":{"googleReviewUrl":"https://evil.example/review"}
        }):
            self.assertEqual(http._google_review_url(),http.GOOGLE_REVIEW_FALLBACK_URL)

    def test_dashboard_review_defaults_to_five_stars_before_google_confirmation(self):
        h=Handler("/compte")
        with patch.object(http,"_account",return_value=("session-token",self.account())), \
             patch.object(http.customer_accounts,"csrf_token",return_value="c"*64), \
             patch.object(http,"_google_review_url",return_value="https://g.page/r/example/review"):
            self.assertTrue(http.handle(h))
        body=h.response["data"].decode()
        self.assertEqual(body.count('class="review-star selected"'),5)
        self.assertIn('data-rating="5" role="radio" aria-checked="true"',body)
        self.assertIn("5 étoiles sélectionnées par défaut.",body)
        self.assertIn("Le commentaire reste vide tant que vous ne le saisissez pas dans Google.",body)
        self.assertIn('href="https://g.page/r/example/review"',body)
        self.assertIn("Google demande la confirmation finale de la note.",body)

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
        begin.assert_called_once_with("google","https://stage.example",browser_binding=binding,mobile=False,return_to="")
        self.assertIn("__Host-checkupauto_oidc_google_sssssssssssssssssssssssssssssssssssssssssss=",h.response["cookies"][0])
        self.assertIn("HttpOnly; Secure; SameSite=Lax",h.response["cookies"][0])

    def test_login_and_oidc_preserve_booking_return_target(self):
        from urllib.parse import urlencode
        booking="/go/booking?service=Contr%C3%B4le+technique&preferredDate=2026-10-08&preferredTime=10%3A30"
        passage="/compte/reserver?"+urlencode({"returnTo":booking})
        login=Handler("/compte?"+urlencode({"returnTo":passage}))
        with patch.object(http,"_account",return_value=("",None)), \
             patch.object(http.customer_oidc,"provider_status",return_value=[
                 {"id":"google","label":"Google","configured":True},
                 {"id":"apple","label":"Apple","configured":False},
             ]):
            self.assertTrue(http.handle(login))
        body=login.response["data"].decode()
        self.assertIn("Connectez-vous ou créez votre compte.",body)
        self.assertIn("créer votre compte par e-mail et mot de passe",body)
        self.assertIn("/auth/customer/google?",body)
        self.assertIn("returnTo=",body)

        auth=Handler("/auth/customer/google?"+urlencode({"returnTo":passage}))
        with patch.object(http.customer_oidc,"begin",return_value="https://accounts.example/auth?state="+"s"*43) as begin:
            self.assertTrue(http.handle(auth))
        binding=auth.response["cookies"][0].split("=",1)[1].split(";",1)[0]
        begin.assert_called_once_with(
            "google","https://stage.example",browser_binding=binding,mobile=False,return_to=passage
        )

    def test_oidc_callback_returns_to_booking_client_step(self):
        passage="/compte/reserver?returnTo=%2Fgo%2Fbooking%3Fservice%3DContr%25C3%25B4le%2Btechnique%26preferredDate%3D2026-10-08%26preferredTime%3D10%253A30"
        h=Handler("/auth/customer/google/callback?state="+"s"*43+"&code=c",headers={"Cookie":"__Host-checkupauto_oidc_google_"+"s"*43+"="+"b"*43})
        with patch.object(http.customer_oidc,"complete",return_value={
            "account":self.account(),"session":{"token":"opaque-session-token","maxAge":43200},
            "returnTo":passage,
        }):
            self.assertTrue(http.handle(h))
        self.assertEqual(h.response["status"],303)
        self.assertEqual(h.response["headers"]["Location"],passage)

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

    def test_native_apple_customer_auth_completes_verified_identity(self):
        payload={
            "identityToken":"jwt-token",
            "authorizationCode":"auth-code",
            "userIdentifier":"apple-subject-42",
            "givenName":"Alice",
            "familyName":"Martin",
            "email":"alice@example.test",
            "nonce":"nonce-42",
        }
        h=Handler("/api/mobile/auth/apple","POST",payload)
        account={**self.account(),"accountId":"00000000-0000-4000-8000-000000000042"}
        with patch.object(http.customer_oidc,"verify_native_apple_identity",return_value={
                 "sub":"apple-subject-42",
                 "email":"alice@example.test",
                 "email_verified":"true",
             }) as verify, \
             patch.object(http.customer_accounts,"create_from_verified_identity",return_value=account) as create, \
             patch.object(http.customer_accounts,"issue_session",return_value={
                 "token":"mobile-session-token",
                 "expiresAt":"2026-10-06T12:00:00+00:00",
             }) as issue:
            self.assertTrue(http.handle(h))
        self.assertEqual(h.response["status"],200)
        self.assertEqual(h.response["json"]["accountId"],account["accountId"])
        self.assertEqual(h.response["json"]["sessionToken"],"mobile-session-token")
        verify.assert_called_once_with("jwt-token",client_id="fr.checkupauto.reminder",nonce="nonce-42")
        create.assert_called_once_with(
            "apple","apple-subject-42","alice@example.test","Alice Martin",email_verified=True
        )
        issue.assert_called_once_with(account["accountId"])

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

    def test_booking_from_customer_space_requires_vehicle_and_contact_confirmation_page(self):
        return_to="/go/booking?service=Contr%C3%B4le+technique&preferredDate=2026-10-08&preferredTime=10%3A30"
        from urllib.parse import urlencode
        h=Handler("/compte/reserver?"+urlencode({"returnTo":return_to}),headers={"Cookie":"checkupauto_customer=token"})
        passage={
            "passageToken":"p"*43,
            "expiresAt":"2026-10-05T12:00:00+00:00",
            "contactDetailsComplete":True,
        }
        vehicle={"vehicleId":"11111111-1111-4111-8111-111111111111","registrationSystem":"siv","registration":"AA-123-AA"}
        with patch.object(http,"_account",return_value=("token",self.account())), \
             patch.object(http.customer_accounts,"begin_passage_confirmation",return_value=passage) as begin, \
             patch.object(http.customer_accounts,"profile",return_value=self.account()), \
             patch.object(http.customer_accounts,"list_vehicles",return_value=[vehicle]), \
             patch.object(http.customer_accounts,"csrf_token",return_value="c"*64):
            self.assertTrue(http.handle(h))
        body=h.response["data"].decode()
        self.assertEqual(h.response["status"],200)
        self.assertIn("Votre véhicule pour ce contrôle",body)
        self.assertIn("Numéro de formule",body)
        self.assertIn("Date d’établissement de la carte grise",body)
        self.assertIn("SIV · AA-123-AA",body)
        self.assertIn("Contrôle technique",body)
        self.assertIn("2026-10-08",body)
        self.assertIn("10:30",body)
        begin.assert_called_once_with(self.account()["accountId"],return_to)

    def test_anonymous_booking_step_redirects_to_login_and_preserves_selected_slot(self):
        return_to="/go/booking?service=Contr%C3%B4le+technique&preferredDate=2026-10-08&preferredTime=10%3A30"
        from urllib.parse import urlencode
        passage="/compte/reserver?"+urlencode({"returnTo":return_to})
        h=Handler(passage)
        with patch.object(http,"_account",return_value=("",None)):
            self.assertTrue(http.handle(h))
        self.assertEqual(h.response["status"],303)
        self.assertTrue(h.response["location"].startswith("/compte?returnTo="))
        self.assertIn("%2Fcompte%2Freserver",h.response["location"])

    def test_confirmed_passage_is_validated_but_not_consumed_before_reservation(self):
        token="p"*43
        return_to="/go/booking?service=Contr%C3%B4le+technique&preferredDate=2026-10-08&preferredTime=10%3A30"
        from urllib.parse import urlencode
        h=Handler("/compte/reserver?"+urlencode({"returnTo":return_to})+"&passage="+token,headers={"Cookie":"checkupauto_customer=token"})
        with patch.object(http,"_account",return_value=("token",self.account())), \
             patch.object(http.customer_accounts,"validate_passage_confirmation",return_value={"ok":True}) as validate:
            self.assertTrue(http.handle(h))
        self.assertEqual(h.response["status"],303)
        self.assertEqual(h.response["location"],return_to)
        validate.assert_called_once_with(self.account()["accountId"],token,return_to)

    def test_vehicle_confirmation_returns_selected_booking_handoff(self):
        passage="p"*43
        vehicle_id="11111111-1111-4111-8111-111111111111"
        return_to="/go/booking?service=Contr%C3%B4le+technique&preferredDate=2026-10-08&preferredTime=10%3A30"
        h=Handler("/api/customer/passage/confirm","POST",{
            "passageToken":passage,
            "returnTo":return_to,
            "action":"validated",
            "vehicleMode":"existing",
            "vehicleId":vehicle_id,
        },headers={
            "Cookie":"checkupauto_customer=token",
            "X-CheckupAuto-Customer-CSRF":"c"*64,
        })
        vehicle={"vehicleId":vehicle_id,"registrationSystem":"siv","registration":"AA-123-AA"}
        with patch.object(http,"_account",return_value=("token",self.account())), \
             patch.object(http.customer_accounts,"verify_csrf",return_value=True), \
             patch.object(http.customer_accounts,"vehicle_summary",return_value=vehicle) as summary, \
             patch.object(http.customer_accounts,"confirm_passage_contact",return_value={"confirmed":True}) as confirm:
            self.assertTrue(http.handle(h))
        self.assertEqual(h.response["status"],200)
        self.assertEqual(h.response["json"]["continueUrl"],return_to)
        summary.assert_called_once_with(self.account()["accountId"],vehicle_id)
        confirm.assert_called_once_with(
            self.account()["accountId"],passage,action="validated",
            vehicle_id=vehicle_id,booking_target=return_to,
        )

    def test_new_siv_vehicle_is_saved_before_booking_confirmation(self):
        passage="p"*43
        vehicle_id="22222222-2222-4222-8222-222222222222"
        return_to="/go/booking?service=Contr%C3%B4le+technique&preferredDate=2026-10-08&preferredTime=10%3A30"
        h=Handler("/api/customer/passage/confirm","POST",{
            "passageToken":passage,"returnTo":return_to,"action":"validated",
            "vehicleMode":"new","registrationSystem":"siv","registration":"AA-123-AA",
            "formulaNumber":"AB12CD34EF5","cardIssueDate":"",
        },headers={"Cookie":"checkupauto_customer=token","X-CheckupAuto-Customer-CSRF":"c"*64})
        with patch.object(http,"_account",return_value=("token",self.account())), \
             patch.object(http.customer_accounts,"verify_csrf",return_value=True), \
             patch.object(http.customer_accounts,"save_vehicle",return_value={"vehicleId":vehicle_id}) as save, \
             patch.object(http.customer_accounts,"confirm_passage_contact",return_value={"confirmed":True}) as confirm:
            self.assertTrue(http.handle(h))
        self.assertEqual(h.response["status"],200)
        save.assert_called_once_with(
            self.account()["accountId"],registration_system="siv",
            registration="AA-123-AA",formula_number="AB12CD34EF5",card_issue_date="",
        )
        confirm.assert_called_once_with(
            self.account()["accountId"],passage,action="validated",
            vehicle_id=vehicle_id,booking_target=return_to,
        )

    def test_booking_confirmation_redirect_requires_complete_slot_target(self):
        valid="/go/booking?service=Contr%C3%B4le+technique&preferredDate=2026-10-08&preferredTime=10%3A30"
        safe=http.booking_confirmation_url(valid)
        self.assertTrue(safe.startswith("/compte/reserver?returnTo="))
        self.assertEqual(http.booking_confirmation_url("/go/booking?service=Contr%C3%B4le+technique"),"/compte/reserver")
        self.assertEqual(http.booking_confirmation_url("https://evil.example/go/booking"),"/compte/reserver")

    def test_authenticated_booking_consumes_confirmation_for_exact_slot(self):
        target="/go/booking?service=Contr%C3%B4le+technique&preferredDate=2026-10-08&preferredTime=10%3A30"
        h=Handler(target,headers={"Cookie":"checkupauto_customer=token"})
        vehicle={"vehicleId":"11111111-1111-4111-8111-111111111111","registrationSystem":"siv","registration":"AA-123-AA"}
        with patch.object(http,"_account",return_value=("token",self.account())), \
             patch.object(http.customer_accounts,"consume_latest_passage_confirmation",return_value={
                 "consumed":True,"confirmedAt":"2026-10-05T12:00:00+00:00",
                 "vehicleId":vehicle["vehicleId"],"vehicle":vehicle,
             }) as consume:
            result=http.consume_booking_confirmation(h,target)
        self.assertTrue(result["required"])
        self.assertEqual(result["vehicle"]["registration"],"AA-123-AA")
        consume.assert_called_once_with(self.account()["accountId"],target)

    def test_modified_contact_and_fni_vehicle_are_saved_together(self):
        passage="p"*43
        vehicle_id="33333333-3333-4333-8333-333333333333"
        return_to="/go/booking?service=V%C3%A9hicule+am%C3%A9nag%C3%A9&preferredDate=2026-10-09&preferredTime=14%3A00"
        payload={
            "passageToken":passage,"returnTo":return_to,"action":"modified","vehicleMode":"new",
            "phone":"0699999999","addressLine1":"20 avenue du Centre",
            "addressLine2":"Bâtiment A","postalCode":"78130","city":"Les Mureaux",
            "registrationSystem":"fni","registration":"1234 AB 78",
            "formulaNumber":"","cardIssueDate":"2008-05-17",
        }
        h=Handler("/api/customer/passage/confirm","POST",payload,headers={
            "Cookie":"checkupauto_customer=token","X-CheckupAuto-Customer-CSRF":"c"*64,
        })
        with patch.object(http,"_account",return_value=("token",self.account())), \
             patch.object(http.customer_accounts,"verify_csrf",return_value=True), \
             patch.object(http.customer_accounts,"update_contact_details",return_value=self.account()) as update, \
             patch.object(http.customer_accounts,"save_vehicle",return_value={"vehicleId":vehicle_id}) as save, \
             patch.object(http.customer_accounts,"confirm_passage_contact",return_value={"confirmed":True}) as confirm:
            self.assertTrue(http.handle(h))
        self.assertEqual(h.response["status"],200)
        update.assert_called_once()
        save.assert_called_once_with(
            self.account()["accountId"],registration_system="fni",
            registration="1234 AB 78",formula_number="",card_issue_date="2008-05-17",
        )
        confirm.assert_called_once_with(
            self.account()["accountId"],passage,action="modified",
            vehicle_id=vehicle_id,booking_target=return_to,
        )

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

