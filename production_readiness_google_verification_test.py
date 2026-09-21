import unittest

import production_readiness as readiness


def integration_status(connectors, *, oauth=True, redirect_allowed=True):
    return {
        "oauthAuthorized": oauth,
        "oauthHealth": {
            "state": "ready" if oauth else "awaiting_authorization",
            "usable": oauth,
        },
        "oauthClient": {
            "configured": oauth,
            "webClientVerified": oauth,
            "redirectUriAllowed": redirect_allowed,
            "redirectUriCount": 1 if oauth else 0,
        },
        "connectors": connectors,
    }


class GoogleIntegrationReadinessTest(unittest.TestCase):
    def test_failed_remote_probe_degrades_even_with_usable_oauth(self):
        component = readiness._google_integration_component(integration_status([
            {"id": "analytics", "connected": False, "verification": "failed", "verificationSource": "remote_api"},
            {"id": "calendar", "connected": True},
        ]))

        self.assertEqual(component["state"], "degraded")
        self.assertFalse(component["critical"])
        self.assertEqual(component["metrics"]["failedVerifications"], 1)
        self.assertEqual(component["metrics"]["unavailableVerifications"], 0)
        self.assertEqual(component["metrics"]["verifiedConnectors"], 0)
        self.assertEqual(component["metrics"]["remoteCheckedConnectors"], 1)
        self.assertIn("refusé", component["detail"])

    def test_unavailable_remote_probe_degrades_without_becoming_critical(self):
        component = readiness._google_integration_component(integration_status([
            {"id": "business_profile", "connected": False, "verification": "unavailable", "verificationSource": "remote_api"},
        ]))

        self.assertEqual(component["state"], "degraded")
        self.assertFalse(component["critical"])
        self.assertEqual(component["metrics"]["unavailableVerifications"], 1)
        self.assertEqual(component["metrics"]["remoteCheckedConnectors"], 1)
        self.assertEqual(component["metrics"]["operationalCheckedConnectors"], 0)
        self.assertIn("indisponible", component["detail"])

    def test_unverified_configuration_connector_degrades_without_claiming_remote_check(self):
        component = readiness._google_integration_component(integration_status([
            {"id": "maps_places", "connected": False, "verification": "unverified", "verificationSource": "configuration"},
        ]))

        self.assertEqual(component["state"], "degraded")
        self.assertFalse(component["critical"])
        self.assertEqual(component["metrics"]["unverifiedVerifications"], 1)
        self.assertEqual(component["metrics"]["remoteCheckedConnectors"], 0)
        self.assertEqual(component["metrics"]["configurationOnlyConnectors"], 1)
        self.assertIn("sans preuve de vérification exploitable", component["detail"])

    def test_verified_remote_connector_is_ready(self):
        component = readiness._google_integration_component(integration_status([
            {"id": "analytics", "connected": True, "verification": "verified", "verificationSource": "remote_api"},
        ]))

        self.assertEqual(component["state"], "ready")
        self.assertEqual(component["metrics"]["verifiedConnectors"], 1)
        self.assertEqual(component["metrics"]["connectedConnectors"], 1)
        self.assertEqual(component["metrics"]["remoteCheckedConnectors"], 1)
        self.assertEqual(component["metrics"]["operationalCheckedConnectors"], 0)

    def test_verified_gmail_delivery_is_operational_not_remote_api(self):
        component = readiness._google_integration_component(integration_status([
            {"id": "gmail", "connected": True, "verification": "verified", "verificationSource": "operational_delivery"},
        ]))

        self.assertEqual(component["state"], "ready")
        self.assertEqual(component["metrics"]["verifiedConnectors"], 1)
        self.assertEqual(component["metrics"]["remoteCheckedConnectors"], 0)
        self.assertEqual(component["metrics"]["operationalCheckedConnectors"], 1)

    def test_unverified_gmail_delivery_degrades_without_claiming_any_check(self):
        component = readiness._google_integration_component(integration_status([
            {"id": "gmail", "connected": False, "verification": "unverified", "verificationSource": "operational_delivery"},
        ]))

        self.assertEqual(component["state"], "degraded")
        self.assertEqual(component["metrics"]["remoteCheckedConnectors"], 0)
        self.assertEqual(component["metrics"]["operationalCheckedConnectors"], 0)
        self.assertEqual(component["metrics"]["unverifiedVerifications"], 1)

    def test_legacy_gmail_payload_is_inferred_as_operational(self):
        component = readiness._google_integration_component(integration_status([
            {"id": "gmail", "connected": True, "verification": "verified"},
        ]))

        self.assertEqual(component["metrics"]["remoteCheckedConnectors"], 0)
        self.assertEqual(component["metrics"]["operationalCheckedConnectors"], 1)

    def test_unprobed_connected_connector_remains_ready_until_probe_exists(self):
        component = readiness._google_integration_component(integration_status([
            {"id": "calendar", "connected": True},
        ]))

        self.assertEqual(component["state"], "ready")
        self.assertEqual(component["metrics"]["remoteCheckedConnectors"], 0)
        self.assertEqual(component["metrics"]["operationalCheckedConnectors"], 0)

    def test_non_oauth_connected_connector_does_not_require_web_callback(self):
        component = readiness._google_integration_component(integration_status(
            [{"id": "maps_places", "connected": True}],
            oauth=False,
            redirect_allowed=False,
        ))

        self.assertEqual(component["state"], "ready")
        self.assertFalse(component["metrics"]["oauthAuthorized"])


if __name__ == "__main__":
    unittest.main()
