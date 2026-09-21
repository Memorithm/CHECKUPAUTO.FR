from pathlib import Path

hub_path = Path("integration_hub.py")
text = hub_path.read_text()

old_client = '''def _client_payload(payload):
    if not isinstance(payload, dict):
        raise IntegrationError("Le fichier OAuth Google est invalide.")
    cfg = payload.get("web") or payload.get("installed") or payload
    if not isinstance(cfg, dict):
        raise IntegrationError("Le fichier OAuth Google est invalide.")
    client_id = str(cfg.get("client_id") or "").strip()
    client_secret = str(cfg.get("client_secret") or "").strip()
    if not client_id or not client_secret:
        raise IntegrationError("client_id et client_secret Google sont requis.")
    token_uri = str(cfg.get("token_uri") or TOKEN_URL).strip()
    if token_uri != TOKEN_URL:
        raise IntegrationError("token_uri OAuth Google non approuvée.")
    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "project_id": str(cfg.get("project_id") or "").strip(),
        "auth_uri": AUTH_URL,
        "token_uri": TOKEN_URL,
    }
'''
new_client = '''def _web_redirect_uris(client):
    if not isinstance(client, dict) or client.get("client_type") != "web":
        return set()
    raw = client.get("redirect_uris")
    if not isinstance(raw, list):
        return set()
    return {str(value).strip() for value in raw if isinstance(value, str) and value.strip()}


def _client_payload(payload):
    if not isinstance(payload, dict):
        raise IntegrationError("Le fichier OAuth Google est invalide.")
    cfg = payload.get("web")
    if not isinstance(cfg, dict):
        if isinstance(payload.get("installed"), dict):
            raise IntegrationError("Utilisez un client OAuth Google de type Application Web.")
        raise IntegrationError("Le fichier OAuth Google doit contenir une configuration web.")
    client_id = str(cfg.get("client_id") or "").strip()
    client_secret = str(cfg.get("client_secret") or "").strip()
    if not client_id or not client_secret:
        raise IntegrationError("client_id et client_secret Google sont requis.")
    token_uri = str(cfg.get("token_uri") or TOKEN_URL).strip()
    if token_uri != TOKEN_URL:
        raise IntegrationError("token_uri OAuth Google non approuvée.")
    raw_redirects = cfg.get("redirect_uris")
    if not isinstance(raw_redirects, list):
        raise IntegrationError("Le client OAuth Google Web doit déclarer ses URI de redirection.")
    redirect_uris = []
    for value in raw_redirects:
        if not isinstance(value, str):
            raise IntegrationError("URI de redirection OAuth Google invalide.")
        uri = value.strip()
        if not uri or len(uri) > 2048:
            raise IntegrationError("URI de redirection OAuth Google invalide.")
        if uri not in redirect_uris:
            redirect_uris.append(uri)
    if not redirect_uris:
        raise IntegrationError("Le client OAuth Google Web doit déclarer ses URI de redirection.")
    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "project_id": str(cfg.get("project_id") or "").strip(),
        "auth_uri": AUTH_URL,
        "token_uri": TOKEN_URL,
        "client_type": "web",
        "redirect_uris": redirect_uris,
    }
'''
if old_client not in text:
    raise SystemExit("expected _client_payload block not found")
text = text.replace(old_client, new_client, 1)

old_info = '''def oauth_client_info():
    cfg = _load(CLIENT_FILE)
    return {
        "configured": bool(cfg.get("client_id") and cfg.get("client_secret")),
        "clientIdSuffix": cfg.get("client_id", "")[-18:] if cfg.get("client_id") else None,
        "projectId": cfg.get("project_id") or None,
    }
'''
new_info = '''def oauth_client_info():
    cfg = _load(CLIENT_FILE)
    redirects = _web_redirect_uris(cfg)
    return {
        "configured": bool(cfg.get("client_id") and cfg.get("client_secret")),
        "webClientVerified": bool(redirects),
        "redirectUriCount": len(redirects),
        "clientIdSuffix": cfg.get("client_id", "")[-18:] if cfg.get("client_id") else None,
        "projectId": cfg.get("project_id") or None,
    }
'''
if old_info not in text:
    raise SystemExit("expected oauth_client_info block not found")
text = text.replace(old_info, new_info, 1)

old_auth = '''    redirect_uri = base_url.rstrip("/") + "/api/integrations/google/oauth/callback"
    state = secrets.token_urlsafe(32)
'''
new_auth = '''    redirect_uri = base_url.rstrip("/") + "/api/integrations/google/oauth/callback"
    allowed_redirects = _web_redirect_uris(client)
    if not allowed_redirects:
        raise IntegrationError("Réimportez un client OAuth Google de type Application Web.")
    if redirect_uri not in allowed_redirects:
        raise IntegrationError("L’URI de redirection OAuth CheckupAuto n’est pas autorisée dans le client Google.")
    state = secrets.token_urlsafe(32)
'''
if old_auth not in text:
    raise SystemExit("expected authorization redirect block not found")
text = text.replace(old_auth, new_auth, 1)

old_callback = '''    client = _load(CLIENT_FILE)
    try:
        response = requests.post(
'''
new_callback = '''    client = _load(CLIENT_FILE)
    if redirect_uri not in _web_redirect_uris(client):
        raise IntegrationError("Le client OAuth Google Web ne permet pas cette URI de redirection.")
    try:
        response = requests.post(
'''
if old_callback not in text:
    raise SystemExit("expected callback client block not found")
text = text.replace(old_callback, new_callback, 1)
hub_path.write_text(text)

test_path = Path("integration_hub_test.py")
tests = test_path.read_text()
old_helper = '''                "project_id": "cybercheck-test",
                "token_uri": hub.TOKEN_URL,
            }
        })
'''
new_helper = '''                "project_id": "cybercheck-test",
                "token_uri": hub.TOKEN_URL,
                "redirect_uris": ["https://www.checkupauto.fr/api/integrations/google/oauth/callback"],
            }
        })
'''
if old_helper not in tests:
    raise SystemExit("expected install_client helper block not found")
test_path.write_text(tests.replace(old_helper, new_helper, 1))

Path("integration_hub_web_oauth_policy_test.py").write_text('''import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

import integration_hub as hub

CALLBACK = "https://www.checkupauto.fr/api/integrations/google/oauth/callback"


class IntegrationHubWebOAuthPolicyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        hub.PRIVATE_DIR = root
        hub.INTEGRATION_DIR = root / "integrations"
        hub.CLIENT_FILE = hub.INTEGRATION_DIR / "google-oauth-client.json"
        hub.TOKEN_FILE = hub.INTEGRATION_DIR / "google-oauth-token.json"
        hub.SETTINGS_FILE = hub.INTEGRATION_DIR / "google-settings.json"
        hub.STATE_FILE = hub.INTEGRATION_DIR / "google-oauth-state.json"

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def web_client(redirects=None):
        return {
            "web": {
                "client_id": "client-id.apps.googleusercontent.com",
                "client_secret": "secret-value",
                "project_id": "cybercheck-test",
                "token_uri": hub.TOKEN_URL,
                "redirect_uris": list(redirects if redirects is not None else [CALLBACK]),
            }
        }

    def test_rejects_installed_desktop_client(self):
        with self.assertRaisesRegex(hub.IntegrationError, "Application Web"):
            hub.save_oauth_client({"installed": {
                "client_id": "desktop.apps.googleusercontent.com",
                "client_secret": "secret-value",
                "token_uri": hub.TOKEN_URL,
                "redirect_uris": ["http://localhost"],
            }})
        self.assertFalse(hub.CLIENT_FILE.exists())

    def test_rejects_flat_untyped_client(self):
        with self.assertRaisesRegex(hub.IntegrationError, "configuration web"):
            hub.save_oauth_client({
                "client_id": "legacy.apps.googleusercontent.com",
                "client_secret": "secret-value",
                "token_uri": hub.TOKEN_URL,
            })
        self.assertFalse(hub.CLIENT_FILE.exists())

    def test_web_client_requires_declared_redirect_uri(self):
        with self.assertRaisesRegex(hub.IntegrationError, "URI de redirection"):
            hub.save_oauth_client(self.web_client([]))

    def test_saved_web_client_reports_secret_free_policy_state(self):
        info = hub.save_oauth_client(self.web_client())
        self.assertTrue(info["configured"])
        self.assertTrue(info["webClientVerified"])
        self.assertEqual(info["redirectUriCount"], 1)
        self.assertNotIn("client_secret", info)

    def test_authorization_uses_exact_registered_callback(self):
        hub.save_oauth_client(self.web_client())
        result = hub.create_authorization_url("https://www.checkupauto.fr", ["analytics"])
        params = parse_qs(urlparse(result["authorizationUrl"]).query)
        self.assertEqual(params["redirect_uri"], [CALLBACK])

    def test_authorization_rejects_unregistered_callback_before_state_write(self):
        hub.save_oauth_client(self.web_client())
        with self.assertRaisesRegex(hub.IntegrationError, "n’est pas autorisée"):
            hub.create_authorization_url("https://staging.checkupauto.fr", ["analytics"])
        self.assertFalse(hub.STATE_FILE.exists())

    def test_legacy_normalized_client_can_refresh_but_cannot_start_new_authorization(self):
        hub._atomic_json(hub.CLIENT_FILE, {
            "client_id": "legacy.apps.googleusercontent.com",
            "client_secret": "legacy-secret",
            "project_id": "legacy-project",
            "token_uri": hub.TOKEN_URL,
        })
        hub._atomic_json(hub.TOKEN_FILE, {
            "refresh_token": "refresh",
            "scope": "https://www.googleapis.com/auth/analytics.readonly",
        })
        self.assertTrue(hub.oauth_health()["usable"])
        self.assertFalse(hub.oauth_client_info()["webClientVerified"])
        with self.assertRaisesRegex(hub.IntegrationError, "Application Web"):
            hub.create_authorization_url("https://www.checkupauto.fr", ["analytics"])
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"access_token": "new-access", "expires_in": 3600}
        with patch("integration_hub.requests.post", return_value=response):
            token = hub.google_access_token(
                ["https://www.googleapis.com/auth/analytics.readonly"], force_refresh=True
            )
        self.assertEqual(token, "new-access")

    def test_callback_fails_closed_if_web_client_policy_is_lost(self):
        hub.save_oauth_client(self.web_client())
        auth = hub.create_authorization_url("https://www.checkupauto.fr", ["analytics"])
        state = parse_qs(urlparse(auth["authorizationUrl"]).query)["state"][0]
        hub._atomic_json(hub.CLIENT_FILE, {
            "client_id": "legacy.apps.googleusercontent.com",
            "client_secret": "legacy-secret",
            "token_uri": hub.TOKEN_URL,
        })
        with patch("integration_hub.requests.post") as post:
            with self.assertRaisesRegex(hub.IntegrationError, "client OAuth Google Web"):
                hub.handle_oauth_callback("https://www.checkupauto.fr", state, "code")
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
''')
