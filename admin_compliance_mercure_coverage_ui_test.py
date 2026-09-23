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
        self.assertIn("PREUVE SHA-256", SCRIPT)
        self.assertIn("esc(evidence)", SCRIPT)
        self.assertNotIn("CYBERCHECK_MERCURE_DSAR_COVERAGE_EVIDENCE", SCRIPT)
        self.assertIn("aucune preuve brute", SCRIPT)

    def test_vehicle_coverage_stays_fail_closed(self):
        self.assertIn("Inventaire exhaustif non prouvé", SCRIPT)
        self.assertIn("source autoritaire client→tous véhicules", SCRIPT)
        self.assertIn("PARTIEL", SCRIPT)

    def test_widget_is_inserted_once_next_to_compliance_status(self):
        self.assertIn("#complianceMercureProviderCoverage", SCRIPT)
        self.assertIn("box.id='complianceMercureProviderCoverage'", SCRIPT)
        self.assertIn("anchor.insertAdjacentElement('afterend',box)", SCRIPT)
        self.assertIn("renderMercureProviderCoverage();", SCRIPT)


if __name__ == "__main__":
    unittest.main()
