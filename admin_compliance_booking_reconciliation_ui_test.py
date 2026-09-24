import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class AdminComplianceBookingReconciliationUiTest(unittest.TestCase):
    def test_register_page_exposes_bounded_booking_reconciliation_diagnostics(self):
        html = (ROOT / "admin" / "compliance-registers.html").read_text(encoding="utf-8")
        script = (ROOT / "admin" / "compliance-registers.js").read_text(encoding="utf-8")

        for element_id in (
            "bookingSyntheticObservability",
            "bookingSyntheticState",
            "bookingSyntheticResidual",
            "bookingSyntheticWithoutAttribution",
            "bookingProviderInference",
            "bookingProviderCoverage",
            "bookingSyntheticDiagnostic",
        ):
            self.assertIn(f'id="{element_id}"', html)

        self.assertIn("bookingConversionReconciliation", script)
        self.assertIn("localResidualRows", script)
        self.assertIn("syntheticRowsWithoutAttribution", script)
        self.assertIn("providerIdInferenceUsed===true", script)
        self.assertIn("providerCoverageProven===true", script)
        self.assertIn("Ce résultat ne prouve pas que Mercure", script)
        self.assertIn("textContent", script)
        self.assertNotIn("bookingSyntheticObservability').innerHTML", script)

    def test_ui_never_labels_zero_local_residuals_as_provider_complete(self):
        script = (ROOT / "admin" / "compliance-registers.js").read_text(encoding="utf-8")

        self.assertIn("AUCUN RÉSIDU LOCAL", script)
        self.assertIn("NON PROUVÉE", script)
        self.assertNotIn("COUVERTURE COMPLÈTE", script)
        self.assertNotIn("Mercure complet", script)


if __name__ == "__main__":
    unittest.main()
