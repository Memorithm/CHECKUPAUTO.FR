import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parent
SCRIPT = (ROOT / "admin" / "compliance.js").read_text(encoding="utf-8")
HTML = (ROOT / "admin" / "index.html").read_text(encoding="utf-8")
SERVER = (ROOT / "admin_server.py").read_text(encoding="utf-8")


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

    def test_private_provider_coverage_form_is_explicit_mfa_admin_surface(self):
        for element_id in (
            "mercureCoverageConfigPanel",
            "mercureCoverageHistoryStart",
            "mercureCoverageFutureDays",
            "mercureCoverageEvidence",
            "mercureCoverageEvidenceFile",
            "mercureAppointmentSource",
            "mercureAppointmentEvidence",
            "mercureAppointmentEvidenceFile",
            "mercureVehicleSource",
            "mercureVehicleEvidence",
            "mercureVehicleEvidenceFile",
            "mercureCoverageConfirm",
            "mercureAppointmentConfirm",
            "mercureVehicleConfirm",
            "mercureCoverageSave",
            "mercureCoverageDelete",
        ):
            self.assertIn(f'id="{element_id}"', HTML)
        self.assertIn(
            "/api/admin/compliance/mercure-provider-coverage-config",
            SCRIPT,
        )
        self.assertIn(
            "/api/admin/compliance/mercure-provider-coverage-config",
            SERVER,
        )
        self.assertIn("PROVIDER-BOUNDARY-EVIDENCE-REVIEWED", SCRIPT)
        self.assertIn(
            "PROVIDER-APPOINTMENT-INVENTORY-EVIDENCE-REVIEWED",
            SCRIPT,
        )
        self.assertIn(
            "PROVIDER-VEHICLE-INVENTORY-EVIDENCE-REVIEWED",
            SCRIPT,
        )

    def test_provider_evidence_files_are_hashed_locally_and_never_uploaded(self):
        self.assertIn("MERCURE_EVIDENCE_MAX_BYTES=20*1024*1024", SCRIPT)
        self.assertIn("crypto.subtle.digest('SHA-256'", SCRIPT)
        self.assertIn("file.arrayBuffer()", SCRIPT)
        self.assertIn("Le document brut n’a pas été envoyé", SCRIPT)
        self.assertNotIn("FormData", SCRIPT)
        self.assertNotIn("multipart/form-data", SCRIPT)
        self.assertIn("rawEvidenceStored", SCRIPT)

    def test_provider_config_routes_remain_inside_admin_mfa_boundary(self):
        get_guard = SERVER.index("if path.startswith('/api/admin/'):")
        get_route = SERVER.index(
            "if path=='/api/admin/compliance/mercure-provider-coverage-config':",
            get_guard,
        )
        self.assertLess(get_guard, get_route)

        post = SERVER.index(" def do_POST(self):")
        post_guard = SERVER.index("if path.startswith('/api/admin/'):", post)
        post_route = SERVER.index(
            "if path=='/api/admin/compliance/mercure-provider-coverage-config':",
            post_guard,
        )
        self.assertLess(post_guard, post_route)
        guard_block = SERVER[post_guard:post_route]
        self.assertIn(
            "admin_mfa.configured() and not self._mfa_session_valid()",
            guard_block,
        )

        delete = SERVER.index(" def do_DELETE(self):")
        delete_route = SERVER.index(
            "if path=='/api/admin/compliance/mercure-provider-coverage-config':",
            delete,
        )
        delete_guard = SERVER[delete:delete_route]
        self.assertIn(
            "admin_mfa.configured() and not self._mfa_session_valid()",
            delete_guard,
        )

    def test_widget_is_inserted_once_next_to_compliance_status(self):
        self.assertIn("#complianceMercureProviderCoverage", SCRIPT)
        self.assertIn("box.id='complianceMercureProviderCoverage'", SCRIPT)
        self.assertIn("anchor.insertAdjacentElement('afterend',box)", SCRIPT)
        self.assertIn("renderMercureProviderCoverage();", SCRIPT)


if __name__ == "__main__":
    unittest.main()
