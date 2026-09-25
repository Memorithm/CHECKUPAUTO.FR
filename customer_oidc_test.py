import base64
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

import customer_oidc as oidc


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


class Response:
    def __init__(self, status_code=200, payload=None):
        self.status_code=status_code
        self._payload=payload or {}
    def json(self):
        return self._payload


class CustomerOIDCTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        self.data=root/"data";self.private=root/"private"
        self.data.mkdir();self.private.mkdir()
        self.config=root/"oidc.json"
        self.config.write_text(json.dumps({"providers":{
            "google":{"clientId":"google-client","clientSecret":"google-secret"},
            "apple":{"clientId":"apple-client","clientSecret":"apple-secret"},
            "microsoft":{"clientId":"ms-client","clientSecret":"ms-secret"},
        }}))
        self.config.chmod(0o600)
        self.env=patch.dict(os.environ,{
            "CYBERCHECK_DATA_DIR":str(self.data),
            "CYBERCHECK_PRIVATE_DIR":str(self.private),
            "CYBERCHECK_CUSTOMER_OIDC_CONFIG_PATH":str(self.config),
        },clear=False)
        self.env.start();self.addCleanup(self.env.stop)
        self.key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        numbers=self.key.public_key().public_numbers()
        self.jwk={
            "kty":"RSA","kid":"kid-1","alg":"RS256",
            "n":b64(numbers.n.to_bytes((numbers.n.bit_length()+7)//8,"big")),
            "e":b64(numbers.e.to_bytes((numbers.e.bit_length()+7)//8,"big")),
        }

    def token(self, *, provider, client_id, nonce, email="client@example.test", email_verified=True):
        issuer=oidc.PROVIDERS[provider].get("issuer")
        if not issuer:
            issuer="https://login.microsoftonline.com/9188040d-6c67-4c5b-b112-36a304b66dad/v2.0"
        header={"alg":"RS256","kid":"kid-1","typ":"JWT"}
        claims={
            "iss":issuer,"aud":client_id,"exp":int(time.time())+600,
            "nonce":nonce,"sub":"subject-123","email":email,"name":"Client Test",
        }
        if provider in {"google","apple"}:
            claims["email_verified"]=email_verified if provider=="google" else str(email_verified).lower()
        head=b64(json.dumps(header,separators=(",",":")).encode())
        body=b64(json.dumps(claims,separators=(",",":")).encode())
        signature=self.key.sign((head+"."+body).encode(),padding.PKCS1v15(),hashes.SHA256())
        return head+"."+body+"."+b64(signature)

    def flow(self, provider="google"):
        url=oidc.begin(provider,"https://stage.example")
        from urllib.parse import urlparse,parse_qs
        q=parse_qs(urlparse(url).query)
        return q["state"][0],q["nonce"][0],url

    def test_provider_status_never_exposes_client_values(self):
        status=oidc.provider_status()
        self.assertEqual({x["id"] for x in status},{"google","apple","microsoft"})
        self.assertTrue(all(x["configured"] for x in status))
        self.assertNotIn("google-client",repr(status))
        self.assertNotIn("google-secret",repr(status))

    def test_begin_uses_state_nonce_pkce_and_expected_response_mode(self):
        state,nonce,url=self.flow("apple")
        self.assertIn("code_challenge=",url)
        self.assertIn("code_challenge_method=S256",url)
        self.assertIn("response_mode=form_post",url)
        self.assertNotIn("apple-secret",url)
        self.assertTrue(state)
        self.assertTrue(nonce)

    def test_complete_verifies_signature_nonce_and_issues_internal_session(self):
        state,nonce,_=self.flow("google")
        id_token=self.token(provider="google",client_id="google-client",nonce=nonce)
        seen={}
        def poster(url,**kwargs):
            seen["data"]=kwargs["data"]
            return Response(payload={"id_token":id_token})
        with patch.object(oidc.customer_accounts,"create_from_verified_identity",return_value={
            "accountId":"a"*8+"-"+ "a"*4+"-"+ "4aaa"+"-"+ "8aaa"+"-"+ "a"*12,
            "displayName":"Client Test",
        }) as create, patch.object(oidc.customer_accounts,"issue_session",return_value={
            "token":"session-token","accountId":"account","expiresAt":"later","maxAge":1,
        }):
            result=oidc.complete(
                "google",state,"authorization-code",
                poster=poster,
                jwks_fetcher=lambda *a,**k:Response(payload={"keys":[self.jwk]}),
            )
        self.assertEqual(result["session"]["token"],"session-token")
        self.assertIn("code_verifier",seen["data"])
        create.assert_called_once_with(
            "google","subject-123","client@example.test","Client Test",email_verified=True,
        )
        with self.assertRaisesRegex(oidc.CustomerOIDCError,"^customer_oidc_state_invalid$"):
            oidc.complete(
                "google",state,"authorization-code",
                poster=poster,
                jwks_fetcher=lambda *a,**k:Response(payload={"keys":[self.jwk]}),
            )

    def test_bad_nonce_or_signature_is_rejected(self):
        state,nonce,_=self.flow("google")
        token=self.token(provider="google",client_id="google-client",nonce="wrong")
        with self.assertRaisesRegex(oidc.CustomerOIDCError,"^customer_oidc_token_invalid$"):
            oidc.complete(
                "google",state,"code",
                poster=lambda *a,**k:Response(payload={"id_token":token}),
                jwks_fetcher=lambda *a,**k:Response(payload={"keys":[self.jwk]}),
            )

    def test_google_and_apple_require_verified_email(self):
        for provider,client in (("google","google-client"),("apple","apple-client")):
            with self.subTest(provider=provider):
                state,nonce,_=self.flow(provider)
                token=self.token(provider=provider,client_id=client,nonce=nonce,email_verified=False)
                with self.assertRaisesRegex(oidc.CustomerOIDCError,"^customer_oidc_email_unverified$"):
                    oidc.complete(
                        provider,state,"code",
                        poster=lambda *a,**k:Response(payload={"id_token":token}),
                        jwks_fetcher=lambda *a,**k:Response(payload={"keys":[self.jwk]}),
                    )

    def test_microsoft_consumer_issuer_is_accepted_after_signature_verification(self):
        state,nonce,_=self.flow("microsoft")
        token=self.token(provider="microsoft",client_id="ms-client",nonce=nonce)
        with patch.object(oidc.customer_accounts,"create_from_verified_identity",return_value={"accountId":"id"}) as create, \
             patch.object(oidc.customer_accounts,"issue_session",return_value={"token":"t"}):
            result=oidc.complete(
                "microsoft",state,"code",
                poster=lambda *a,**k:Response(payload={"id_token":token}),
                jwks_fetcher=lambda *a,**k:Response(payload={"keys":[self.jwk]}),
            )
        self.assertEqual(result["session"]["token"],"t")
        self.assertEqual(create.call_args.args[0],"microsoft")


if __name__=="__main__":
    unittest.main()
