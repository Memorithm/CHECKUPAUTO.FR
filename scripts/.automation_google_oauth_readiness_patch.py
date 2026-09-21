from pathlib import Path

path = Path("production_readiness.py")
text = path.read_text()
old = '''        oauth = bool(integrations.get("oauthAuthorized"))
        oauth_health = integrations.get("oauthHealth") or {}
        oauth_state = str(oauth_health.get("state") or ("ready" if oauth else "awaiting_authorization"))
        connected = sum(1 for item in integrations.get("connectors") or [] if item.get("connected"))
        if oauth or connected:
            google_state = "ready"
            google_detail = f"{connected} connecteur(s) connecté(s)"
        elif oauth_state in {"token_expired", "reauthorization_required", "oauth_client_missing"}:
            google_state = "degraded"
            google_detail = "Session OAuth Google à renouveler"
        else:
            google_state = "configuration_required"
            google_detail = "OAuth Google non configuré"
        components.append(_component(
            "google_integration", "IntegrationHub Google", google_state, google_detail,
            critical=False,
            metrics={
                "oauthAuthorized": oauth,
                "oauthState": oauth_state,
                "connectedConnectors": connected,
            },
        ))
'''
new = '''        oauth = bool(integrations.get("oauthAuthorized"))
        oauth_health = integrations.get("oauthHealth") or {}
        oauth_state = str(oauth_health.get("state") or ("ready" if oauth else "awaiting_authorization"))
        oauth_client = integrations.get("oauthClient") or {}
        web_client_verified = bool(oauth_client.get("webClientVerified"))
        redirect_uri_count = int(oauth_client.get("redirectUriCount") or 0)
        connected = sum(1 for item in integrations.get("connectors") or [] if item.get("connected"))
        if oauth and not web_client_verified:
            google_state = "degraded"
            google_detail = "OAuth actif · client Application Web à réimporter avant toute réautorisation"
        elif oauth or connected:
            google_state = "ready"
            google_detail = f"{connected} connecteur(s) connecté(s)"
        elif oauth_state in {"token_expired", "reauthorization_required", "oauth_client_missing"}:
            google_state = "degraded"
            google_detail = "Session OAuth Google à renouveler"
        else:
            google_state = "configuration_required"
            google_detail = "OAuth Google non configuré"
        components.append(_component(
            "google_integration", "IntegrationHub Google", google_state, google_detail,
            critical=False,
            metrics={
                "oauthAuthorized": oauth,
                "oauthState": oauth_state,
                "webClientVerified": web_client_verified,
                "redirectUriCount": redirect_uri_count,
                "connectedConnectors": connected,
            },
        ))
'''
if old not in text:
    raise SystemExit("expected IntegrationHub readiness block not found")
path.write_text(text.replace(old, new, 1))

test_path = Path("production_readiness_test.py")
tests = test_path.read_text()
old_fixture = '''        mock.patch.object(readiness.integration_hub, "status", return_value={
            "oauthAuthorized": True, "oauthHealth": {"state": "ready", "usable": True}, "connectors": [{"connected": True}],
        }),
'''
new_fixture = '''        mock.patch.object(readiness.integration_hub, "status", return_value={
            "oauthAuthorized": True,
            "oauthHealth": {"state": "ready", "usable": True},
            "oauthClient": {"webClientVerified": True, "redirectUriCount": 1},
            "connectors": [{"connected": True}],
        }),
'''
if old_fixture not in tests:
    raise SystemExit("expected healthy IntegrationHub fixture not found")
tests = tests.replace(old_fixture, new_fixture, 1)
marker = '''    def test_stale_google_oauth_is_degraded_without_blocking_launch(self):
'''
insert = '''    def test_authorized_google_oauth_with_unverified_web_client_is_degraded_without_blocking_launch(self):
        patches = healthy_patches()
        patches[6] = mock.patch.object(readiness.integration_hub, "status", return_value={
            "oauthAuthorized": True,
            "oauthHealth": {"state": "ready", "usable": True},
            "oauthClient": {"configured": True, "webClientVerified": False, "redirectUriCount": 0},
            "connectors": [{"connected": True}],
        })
        result = self._run_with(patches)
        google = next(item for item in result["components"] if item["id"] == "google_integration")
        self.assertEqual(google["state"], "degraded")
        self.assertFalse(google["metrics"]["webClientVerified"])
        self.assertEqual(google["metrics"]["redirectUriCount"], 0)
        self.assertIn("Application Web", google["detail"])
        self.assertTrue(result["activationGate"]["allowed"])

    def test_non_oauth_google_connector_does_not_require_web_client(self):
        patches = healthy_patches()
        patches[6] = mock.patch.object(readiness.integration_hub, "status", return_value={
            "oauthAuthorized": False,
            "oauthHealth": {"state": "awaiting_authorization", "usable": False},
            "oauthClient": {"configured": False, "webClientVerified": False, "redirectUriCount": 0},
            "connectors": [{"connected": True}],
        })
        result = self._run_with(patches)
        google = next(item for item in result["components"] if item["id"] == "google_integration")
        self.assertEqual(google["state"], "ready")
        self.assertFalse(google["metrics"]["webClientVerified"])
        self.assertEqual(google["metrics"]["redirectUriCount"], 0)
        self.assertTrue(result["activationGate"]["allowed"])

'''
if marker not in tests:
    raise SystemExit("expected stale OAuth test marker not found")
test_path.write_text(tests.replace(marker, insert + marker, 1))
