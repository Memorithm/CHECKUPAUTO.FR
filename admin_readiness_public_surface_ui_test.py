from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent
SCRIPT = (ROOT / "admin" / "readiness.js").read_text(encoding="utf-8")


class AdminReadinessPublicSurfaceUITest(unittest.TestCase):
    def test_public_surface_provenance_is_rendered_from_component_metrics(self):
        self.assertIn("renderPublicSurfaceProvenance(components)", SCRIPT)
        self.assertIn("item.id === 'public_site'", SCRIPT)
        for field in (
            "canonicalValid",
            "activationRequested",
            "publicSurfaceProbeState",
            "publicSurfaceVerified",
        ):
            self.assertIn(field, SCRIPT)
        for element_id in (
            "readinessPublicCanonical",
            "readinessPublicActivation",
            "readinessPublicProbe",
            "readinessPublicVerified",
        ):
            self.assertIn(element_id, SCRIPT)

    def test_probe_state_is_bounded_before_rendering(self):
        for state in (
            "verified",
            "deferred",
            "redirected",
            "marker_not_found",
            "unavailable",
            "invalid_marker",
            "surface_mismatch",
            "probe_error",
            "invalid_probe_result",
        ):
            self.assertIn(f"'{state}'", SCRIPT)
        self.assertIn("return labels[state] || 'NON VÉRIFIÉ'", SCRIPT)

    def test_public_surface_copy_does_not_claim_deferred_probe_is_verified(self):
        self.assertIn("PREUVE DE SURFACE", SCRIPT)
        self.assertIn("DIFFÉRÉE", SCRIPT)
        self.assertIn("VÉRIFIÉE", SCRIPT)
        self.assertIn("NON VÉRIFIÉE", SCRIPT)

    def test_panel_uses_safe_dom_rendering(self):
        self.assertIn("document.createElement", SCRIPT)
        self.assertIn("textContent", SCRIPT)
        self.assertNotIn("innerHTML", SCRIPT)

    def test_failed_readiness_clears_public_surface_provenance(self):
        self.assertIn("renderPublicSurfaceProvenance([])", SCRIPT)


if __name__ == "__main__":
    unittest.main()
