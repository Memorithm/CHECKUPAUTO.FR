import unittest
from pathlib import Path


class AdminIntegrationsWebOAuthUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (Path(__file__).parent / "admin" / "integrations.js").read_text()

    def test_admin_surfaces_web_client_verification(self):
        self.assertIn("client.webClientVerified", self.source)
        self.assertIn("client.redirectUriAllowed", self.source)
        self.assertIn("Client OAuth Web vérifié", self.source)
        self.assertIn("Client OAuth historique", self.source)
        self.assertIn("Application Web", self.source)
        self.assertIn("callback CheckupAuto non autorisé", self.source)

    def test_new_authorization_is_disabled_until_web_client_is_verified(self):
        compact = "".join(self.source.split())
        self.assertIn(
            "ih('integrationConnectSelected').disabled=!client.configured||!webClientReady;",
            compact,
        )

    def test_existing_oauth_disconnect_remains_independent_from_web_client_migration(self):
        compact = "".join(self.source.split())
        self.assertIn(
            "ih('integrationDisconnectGoogle').disabled=!data.oauthAuthorized;",
            compact,
        )

    def test_search_console_connector_is_actively_verified(self):
        compact = "".join(self.source.split())
        self.assertIn("ihApplySearchConsoleProbe", self.source)
        self.assertIn("awaitihApi('/api/admin/google/status')", compact)
        self.assertIn("row.verification='verified'", compact)
        self.assertIn("API Search Console vérifiée", self.source)

    def test_failed_search_console_probe_cannot_remain_connected(self):
        compact = "".join(self.source.split())
        unavailable = compact.index("row.verification='unavailable'")
        before = compact.rfind("row.connected=false;", 0, unavailable)
        self.assertGreaterEqual(before, 0)
        failed = compact.index("row.verification='failed'")
        before_failed = compact.rfind("row.connected=false;", 0, failed)
        self.assertGreaterEqual(before_failed, 0)
        self.assertIn("Configuration présente · vérification API Search Console indisponible", self.source)


if __name__ == "__main__":
    unittest.main()
