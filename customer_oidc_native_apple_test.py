import base64
import json
import pytest
import customer_oidc


def _part(value):
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")


def test_native_apple_rejects_wrong_audience_before_acceptance(monkeypatch):
    # Signature/JWKS behavior is already covered by customer_oidc tests.
    # This regression test ensures the native helper forwards the iOS audience
    # rather than reusing the web Services ID.
    seen = {}
    token = _part({"alg":"RS256","kid":"k"}) + "." + _part({"nonce":"n"}) + ".sig"

    def fake_verify(provider, raw, *, client_id, nonce, fetcher=None):
        seen.update(provider=provider, client_id=client_id, nonce=nonce)
        return {"sub":"apple-user","email":"relay@example.com","email_verified":"true"}

    monkeypatch.setattr(customer_oidc, "_verify_id_token", fake_verify)
    claims = customer_oidc.verify_native_apple_identity(
        token, client_id="fr.checkupauto.reminder", nonce="n"
    )
    assert claims["sub"] == "apple-user"
    assert seen == {
        "provider":"apple",
        "client_id":"fr.checkupauto.reminder",
        "nonce":"n",
    }


@pytest.mark.parametrize("client_id", ["", "bad client id", "x"])
def test_native_apple_rejects_invalid_client_id(client_id):
    with pytest.raises(customer_oidc.CustomerOIDCError):
        customer_oidc.verify_native_apple_identity("a.b.c", client_id=client_id, nonce="n")
