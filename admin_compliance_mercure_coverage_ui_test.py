import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parent
SCRIPT = (ROOT / "admin" / "compliance.js").read_text(encoding="utf-8")


class ComplianceMercureCoverageUiTest(unittest.TestCase):
    def test_console_renders_provider_boundary_state(self):
        self.assertIn("snapshot?.mercureProviderCoverage", SCRIPT)
        self.assertIn("boundary.historyStart", SCRIPT)
        self.assertIn("boundary.futureDays", SCRIPT)
        self.assertIn("boundary.evidenceSha256", SCRIPT)
        self.assertIn("ATTESTÉ", SCRIPT)
        self.assertIn("INVALIDE", SCRIPT)
        self.assertIn("NON CONFIGURÉ", SCRIPT)

    def test_only_hashed_provider_evidence_is_rendered(self):
        self.assertIn("PREUVE TEMPORELLE SHA-256", SCRIPT)
        self.assertIn("esc(evidence)", SCRIPT)
        self.assertNotIn("CYBERCHECK_MERCURE_DSAR_COVERAGE_EVIDENCE", SCRIPT)
        self.assertIn("aucune preuve brute", SCRIPT)

    def test_appointment_inventory_attestation_is_rendered_independently_and_fail_closed(self):
        self.assertIn("boundary.appointmentInventory", SCRIPT)
        self.assertIn("appointment.source", SCRIPT)
        self.assertIn("appointment.evidenceSha256", SCRIPT)
        self.assertIn("INVENTAIRE RENDEZ-VOUS", SCRIPT)
        self.assertIn("SOURCE RENDEZ-VOUS", SCRIPT)
        self.assertIn("PREUVE RENDEZ-VOUS SHA-256", SCRIPT)
        self.assertIn("exhaustivité du calendrier sujet", SCRIPT)
        self.assertIn("frontière temporelle seule ne prouve jamais", SCRIPT)
        self.assertIn("reste requise", SCRIPT)
        self.assertNotIn("CYBERCHECK_MERCURE_DSAR_APPOINTMENT_INVENTORY_EVIDENCE", SCRIPT)

    def test_vehicle_attestation_is_rendered_independently_and_fail_closed(self):
        self.assertIn("boundary.vehicleInventory", SCRIPT)
        self.assertIn("vehicle.evidenceSha256", SCRIPT)
        self.assertIn("INVENTAIRE VÉHICULES", SCRIPT)
        self.assertIn("PREUVE VÉHICULE SHA-256", SCRIPT)
        self.assertIn("relation sujet→tous véhicules", SCRIPT)
        self.assertIn("reste requise", SCRIPT)
        self.assertIn("frontière temporelle doit être appliquée", SCRIPT)
        self.assertIn("l’inventaire ne doit pas être tronqué", SCRIPT)
        self.assertNotIn("CYBERCHECK_MERCURE_DSAR_VEHICLE_INVENTORY_EVIDENCE", SCRIPT)

    def test_widget_is_inserted_once_next_to_compliance_status(self):
        self.assertIn("#complianceMercureProviderCoverage", SCRIPT)
        self.assertIn("box.id='complianceMercureProviderCoverage'", SCRIPT)
        self.assertIn("anchor.insertAdjacentElement('afterend',box)", SCRIPT)
        self.assertIn("renderMercureProviderCoverage();", SCRIPT)


if __name__ == "__main__":
    unittest.main()
