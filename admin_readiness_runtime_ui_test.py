from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent
SCRIPT = (ROOT / "admin" / "readiness.js").read_text(encoding="utf-8")


class AdminReadinessRuntimeUITest(unittest.TestCase):
    def test_runtime_provenance_is_rendered_from_readiness_payload(self):
        self.assertIn("renderRuntimeProvenance(data.runtime)", SCRIPT)
        for field in (
            "gitSha",
            "gitShaAvailable",
            "gitBranch",
            "gitDirty",
            "baselineGitSha",
            "baselineMatchesRuntime",
        ):
            self.assertIn(field, SCRIPT)
        for element_id in (
            "readinessRuntimeSha",
            "readinessRuntimeBranch",
            "readinessRuntimeDirty",
            "readinessBaselineSha",
            "readinessBaselineMatch",
        ):
            self.assertIn(element_id, SCRIPT)

    def test_runtime_sha_and_baseline_fail_closed(self):
        self.assertIn("/^[0-9a-f]{40}$/", SCRIPT)
        self.assertIn("runtime.gitShaAvailable === true", SCRIPT)
        self.assertIn("NON VÉRIFIÉ", SCRIPT)
        self.assertIn("runtimeSha && baselineSha && runtime.baselineMatchesRuntime === true", SCRIPT)
        self.assertIn("runtimeSha && baselineSha && runtime.baselineMatchesRuntime === false", SCRIPT)
        self.assertIn("CONFORME", SCRIPT)
        self.assertIn("ÉCART", SCRIPT)

    def test_runtime_dirty_state_is_explicit(self):
        self.assertIn("runtime.gitDirty === false ? 'PROPRE'", SCRIPT)
        self.assertIn("runtime.gitDirty === true ? 'MODIFIÉ'", SCRIPT)

    def test_baseline_copy_does_not_claim_github_freshness(self):
        self.assertIn("dernier main GitHub", SCRIPT)
        self.assertIn("ne prouve pas", SCRIPT)

    def test_runtime_panel_uses_safe_dom_rendering(self):
        self.assertIn("document.createElement", SCRIPT)
        self.assertIn("textContent", SCRIPT)
        self.assertNotIn("innerHTML", SCRIPT)

    def test_failed_readiness_clears_runtime_provenance(self):
        self.assertIn("renderRuntimeProvenance({})", SCRIPT)


if __name__ == "__main__":
    unittest.main()
