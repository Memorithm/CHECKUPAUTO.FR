from pathlib import Path

# IntegrationHub: distinguish a structurally valid Web client from one that
# actually authorizes CheckupAuto's exact callback URL.
path = Path("integration_hub.py")
text = path.read_text()
old = '''def save_oauth_client(payload):
    clean = _client_payload(payload)
    _atomic_json(CLIENT_FILE, clean)
    return oauth_client_info()


def oauth_client_info():
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
new = '''def oauth_redirect_uri(base_url):
    base = str(base_url or "").strip().rstrip("/")
    if not base:
        return ""
    return base + "/api/integrations/google/oauth/callback"


def save_oauth_client(payload):
    clean = _client_payload(payload)
    _atomic_json(CLIENT_FILE, clean)
    return oauth_client_info()


def oauth_client_info(base_url=""):
    cfg = _load(CLIENT_FILE)
    redirects = _web_redirect_uris(cfg)
    expected_redirect = oauth_redirect_uri(base_url)
    return {
        "configured": bool(cfg.get("client_id") and cfg.get("client_secret")),
        "webClientVerified": bool(redirects),
        "redirectUriAllowed": bool(expected_redirect and expected_redirect in redirects),
        "redirectUriCount": len(redirects),
        "clientIdSuffix": cfg.get("client_id", "")[-18:] if cfg.get("client_id") else None,
        "projectId": cfg.get("project_id") or None,
    }
'''
if old not in text:
    raise SystemExit("oauth_client_info block not found")
text = text.replace(old, new, 1)

old = '''def status(legacy_search_console=None):
    legacy_search_console = legacy_search_console or {}
    scopes = _granted_scopes()
    cfg = settings()
    client = oauth_client_info()
    health = oauth_health()
'''
new = '''def status(legacy_search_console=None, base_url=""):
    legacy_search_console = legacy_search_console or {}
    scopes = _granted_scopes()
    cfg = settings()
    client = oauth_client_info(base_url)
    health = oauth_health()
'''
if old not in text:
    raise SystemExit("status signature block not found")
text = text.replace(old, new, 1)

old = '''    redirect_uri = base_url.rstrip("/") + "/api/integrations/google/oauth/callback"
    allowed_redirects = _web_redirect_uris(client)
'''
new = '''    redirect_uri = oauth_redirect_uri(base_url)
    allowed_redirects = _web_redirect_uris(client)
'''
if text.count(old) != 1:
    raise SystemExit("authorization redirect construction block not found exactly once")
text = text.replace(old, new, 1)

old = '''    redirect_uri = base_url.rstrip("/") + "/api/integrations/google/oauth/callback"
    if pending.get("redirect_uri") != redirect_uri:
'''
new = '''    redirect_uri = oauth_redirect_uri(base_url)
    if pending.get("redirect_uri") != redirect_uri:
'''
if text.count(old) != 1:
    raise SystemExit("callback redirect construction block not found exactly once")
text = text.replace(old, new, 1)
path.write_text(text)

# Admin API: status and displayed callback are derived from the same helper.
path = Path("admin_server.py")
text = path.read_text()
old = '''  if path=='/api/admin/integrations/google/status':
   if not self.authorized(): return self.require_auth()
   try:
    result=integrations.status(gsc.credential_info())
    result['redirectUri']=self._request_origin()+'/api/integrations/google/oauth/callback'
    return self.send_json(result)
   except Exception: return self.send_json({'ok':False,'error':'google_integration_status_unavailable'},500)
'''
new = '''  if path=='/api/admin/integrations/google/status':
   if not self.authorized(): return self.require_auth()
   try:
    origin=self._request_origin(); result=integrations.status(gsc.credential_info(),origin)
    result['redirectUri']=integrations.oauth_redirect_uri(origin)
    return self.send_json(result)
   except Exception: return self.send_json({'ok':False,'error':'google_integration_status_unavailable'},500)
'''
if old not in text:
    raise SystemExit("admin IntegrationHub status block not found")
path.write_text(text.replace(old, new, 1))

# Production Readiness: an active OAuth session is migration-ready only when
# the canonical CheckupAuto callback is actually authorized by the Web client.
path = Path("production_readiness.py")
text = path.read_text()
old = '''    integrations, error = _safe("IntegrationHub", lambda: integration_hub.status(gsc_client.credential_info()))
    if error:
'''
new = '''    google_canonical = str((config.get("seo") or {}).get("canonicalUrl") or "").strip()
    google_parsed = urlparse(google_canonical)
    google_origin = f"{google_parsed.scheme}://{google_parsed.netloc}" if google_parsed.scheme and google_parsed.netloc else ""
    integrations, error = _safe(
        "IntegrationHub",
        lambda: integration_hub.status(gsc_client.credential_info(), google_origin),
    )
    if error:
'''
if old not in text:
    raise SystemExit("readiness IntegrationHub call block not found")
text = text.replace(old, new, 1)
old = '''        oauth_client = integrations.get("oauthClient") or {}
        web_client_verified = bool(oauth_client.get("webClientVerified"))
        redirect_uri_count = int(oauth_client.get("redirectUriCount") or 0)
        connected = sum(1 for item in integrations.get("connectors") or [] if item.get("connected"))
        if oauth and not web_client_verified:
            google_state = "degraded"
            google_detail = "OAuth actif · client Application Web à réimporter avant toute réautorisation"
'''
new = '''        oauth_client = integrations.get("oauthClient") or {}
        web_client_verified = bool(oauth_client.get("webClientVerified"))
        redirect_uri_allowed = bool(oauth_client.get("redirectUriAllowed"))
        redirect_uri_count = int(oauth_client.get("redirectUriCount") or 0)
        connected = sum(1 for item in integrations.get("connectors") or [] if item.get("connected"))
        if oauth and not redirect_uri_allowed:
            google_state = "degraded"
            google_detail = "OAuth actif · callback CheckupAuto à autoriser dans le client Application Web"
'''
if old not in text:
    raise SystemExit("readiness Web client state block not found")
text = text.replace(old, new, 1)
old = '''                "webClientVerified": web_client_verified,
                "redirectUriCount": redirect_uri_count,
'''
new = '''                "webClientVerified": web_client_verified,
                "redirectUriAllowed": redirect_uri_allowed,
                "redirectUriCount": redirect_uri_count,
'''
if old not in text:
    raise SystemExit("readiness metrics block not found")
path.write_text(text.replace(old, new, 1))

# Admin UI: do not enable a new authorization merely because some redirect URI exists.
path = Path("admin/integrations.js")
text = path.read_text()
old = '''  const client=data.oauthClient||{};
  const oauthHealth=data.oauthHealth||{};
  const webClientReady=Boolean(client.webClientVerified);
  ih('googleOAuthRedirectUri').textContent=data.redirectUri||'—';
  if(client.configured&&webClientReady){
    ih('googleOAuthIdentity').textContent=`Client OAuth Web vérifié · ${client.projectId||'projet Google'} · …${client.clientIdSuffix||''} · ${ihOauthHealthText(oauthHealth)}`;
  }else if(client.configured){
    ih('googleOAuthIdentity').textContent=`Client OAuth historique · ${ihOauthHealthText(oauthHealth)} · réimporter un client Google « Application Web »`;
    badge.className='gsc-status warning';
  }else{
'''
new = '''  const client=data.oauthClient||{};
  const oauthHealth=data.oauthHealth||{};
  const webClientReady=Boolean(client.webClientVerified&&client.redirectUriAllowed);
  ih('googleOAuthRedirectUri').textContent=data.redirectUri||'—';
  if(client.configured&&webClientReady){
    ih('googleOAuthIdentity').textContent=`Client OAuth Web vérifié · ${client.projectId||'projet Google'} · …${client.clientIdSuffix||''} · ${ihOauthHealthText(oauthHealth)}`;
  }else if(client.configured&&client.webClientVerified){
    ih('googleOAuthIdentity').textContent=`Client OAuth Web · callback CheckupAuto non autorisé · ${ihOauthHealthText(oauthHealth)}`;
    badge.className='gsc-status warning';
  }else if(client.configured){
    ih('googleOAuthIdentity').textContent=`Client OAuth historique · ${ihOauthHealthText(oauthHealth)} · réimporter un client Google « Application Web »`;
    badge.className='gsc-status warning';
  }else{
'''
if old not in text:
    raise SystemExit("admin OAuth render block not found")
path.write_text(text.replace(old, new, 1) + ("\n" if not text.endswith("\n") else ""))

# Tests: exact callback policy in IntegrationHub.
path = Path("integration_hub_web_oauth_policy_test.py")
tests = path.read_text()
marker = '''    def test_authorization_uses_exact_registered_callback(self):
'''
insert = '''    def test_status_distinguishes_web_shape_from_exact_callback_authorization(self):
        hub.save_oauth_client(self.web_client(["https://other.example/api/integrations/google/oauth/callback"]))
        client = hub.status({}, "https://www.checkupauto.fr")["oauthClient"]
        self.assertTrue(client["webClientVerified"])
        self.assertFalse(client["redirectUriAllowed"])
        self.assertEqual(client["redirectUriCount"], 1)

    def test_status_marks_exact_checkupauto_callback_allowed(self):
        hub.save_oauth_client(self.web_client())
        client = hub.status({}, "https://www.checkupauto.fr")["oauthClient"]
        self.assertTrue(client["webClientVerified"])
        self.assertTrue(client["redirectUriAllowed"])

'''
if marker not in tests:
    raise SystemExit("IntegrationHub exact callback test marker not found")
path.write_text(tests.replace(marker, insert + marker, 1))

# Readiness fixtures and regression now use exact redirect authorization.
path = Path("production_readiness_test.py")
tests = path.read_text()
tests = tests.replace(
    '"oauthClient": {"webClientVerified": True, "redirectUriCount": 1},',
    '"oauthClient": {"webClientVerified": True, "redirectUriAllowed": True, "redirectUriCount": 1},',
    1,
)
tests = tests.replace(
    '"oauthClient": {"configured": True, "webClientVerified": False, "redirectUriCount": 0},',
    '"oauthClient": {"configured": True, "webClientVerified": False, "redirectUriAllowed": False, "redirectUriCount": 0},',
    1,
)
tests = tests.replace(
    '"oauthClient": {"configured": False, "webClientVerified": False, "redirectUriCount": 0},',
    '"oauthClient": {"configured": False, "webClientVerified": False, "redirectUriAllowed": False, "redirectUriCount": 0},',
    1,
)
old_asserts = '''        self.assertFalse(google["metrics"]["webClientVerified"])
        self.assertEqual(google["metrics"]["redirectUriCount"], 0)
        self.assertIn("Application Web", google["detail"])
'''
new_asserts = '''        self.assertFalse(google["metrics"]["webClientVerified"])
        self.assertFalse(google["metrics"]["redirectUriAllowed"])
        self.assertEqual(google["metrics"]["redirectUriCount"], 0)
        self.assertIn("Application Web", google["detail"])
'''
if old_asserts not in tests:
    raise SystemExit("readiness unverified assertions block not found")
tests = tests.replace(old_asserts, new_asserts, 1)
marker = '''    def test_non_oauth_google_connector_does_not_require_web_client(self):
'''
insert = '''    def test_authorized_google_oauth_with_wrong_web_redirect_is_degraded(self):
        patches = healthy_patches()
        patches[6] = mock.patch.object(readiness.integration_hub, "status", return_value={
            "oauthAuthorized": True,
            "oauthHealth": {"state": "ready", "usable": True},
            "oauthClient": {"configured": True, "webClientVerified": True, "redirectUriAllowed": False, "redirectUriCount": 1},
            "connectors": [{"connected": True}],
        })
        result = self._run_with(patches)
        google = next(item for item in result["components"] if item["id"] == "google_integration")
        self.assertEqual(google["state"], "degraded")
        self.assertTrue(google["metrics"]["webClientVerified"])
        self.assertFalse(google["metrics"]["redirectUriAllowed"])
        self.assertTrue(result["activationGate"]["allowed"])

'''
if marker not in tests:
    raise SystemExit("non-OAuth readiness test marker not found")
path.write_text(tests.replace(marker, insert + marker, 1))

# Admin contract test follows exact callback authorization, not structural shape only.
path = Path("admin_integrations_web_oauth_ui_test.py")
tests = path.read_text()
tests = tests.replace(
    'self.assertIn("client.webClientVerified", self.source)\n',
    'self.assertIn("client.webClientVerified", self.source)\n        self.assertIn("client.redirectUriAllowed", self.source)\n',
    1,
)
tests = tests.replace(
    '        self.assertIn("Application Web", self.source)\n',
    '        self.assertIn("Application Web", self.source)\n        self.assertIn("callback CheckupAuto non autorisé", self.source)\n',
    1,
)
path.write_text(tests)
