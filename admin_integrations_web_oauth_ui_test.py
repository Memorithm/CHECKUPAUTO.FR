import unittest
from pathlib import Path


class AdminIntegrationsWebOAuthUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (Path(__file__).parent / "admin" / "integrations.js").read_text()

    def test_admin_surfaces_web_client_verification(self):
        self.assertIn("client.webClientVerified", self.source)
        self.assertIn("Client OAuth Web vérifié", self.source)
        self.assertIn("Client OAuth historique", self.source)
        self.assertIn("Application Web", self.source)

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


if __name__ == "__main__":
    unittest.main()
