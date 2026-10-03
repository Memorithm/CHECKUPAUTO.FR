import base64
import json
import unittest
from unittest import mock
import customer_oidc

def _part(value):
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")

class NativeAppleTest(unittest.TestCase):
    def test_native_apple_uses_ios_audience(self):
        seen={}
        nonce="n"*32
        digest=__import__("hashlib").sha256(nonce.encode()).hexdigest()
        token=_part({"alg":"RS256","kid":"k"})+"."+_part({"nonce":digest})+".sig"
        def fake(provider,raw,*,client_id,nonce,fetcher=None):
            seen.update(provider=provider,client_id=client_id,nonce=nonce)
            return {"sub":"apple-user"}
        with mock.patch.object(customer_oidc,"_verify_id_token",side_effect=fake):
            claims=customer_oidc.verify_native_apple_identity(token,client_id="fr.checkupauto.reminder",nonce=nonce)
        self.assertEqual(claims["sub"],"apple-user")
        self.assertEqual(seen["provider"],"apple")
        self.assertEqual(seen["client_id"],"fr.checkupauto.reminder")
        self.assertEqual(seen["nonce"],digest)

    def test_invalid_client_ids(self):
        for client_id in ("","bad client id","x"):
            with self.subTest(client_id=client_id), self.assertRaises(customer_oidc.CustomerOIDCError):
                customer_oidc.verify_native_apple_identity("a.b.c",client_id=client_id,nonce="n"*32)

if __name__=="__main__":
    unittest.main()
