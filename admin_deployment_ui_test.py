from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent


class AdminDeploymentUITest(unittest.TestCase):
    def test_admin_page_exposes_deployment_center_without_embedded_secret(self):
        html = (ROOT / "admin" / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="#deployment"', html)
        self.assertIn('id="deployment"', html)
        self.assertIn('id="deploymentPassword" type="password"', html)
        self.assertIn('/admin/deployment.js', html)
        self.assertNotIn('value="secret', html.lower())
        self.assertNotIn('planethoster_password', html.lower())

    def test_deployment_javascript_never_rehydrates_password_from_api(self):
        script = (ROOT / "admin" / "deployment.js").read_text(encoding="utf-8")
        self.assertIn("$('deploymentPassword').value = ''", script)
        self.assertIn("/api/admin/deployment/status", script)
        self.assertIn("/api/admin/deployment/job", script)
        self.assertIn("/api/admin/deployment/update-status", script)
        self.assertIn("deploymentSourceState", script)
        self.assertIn("sourceBuildCapable", script)
        self.assertIn("source_unavailable", script)
        self.assertIn("deploymentUpdateState", script)
        self.assertIn("deploymentRollbackCandidates", script)
        self.assertNotIn("credential.password", script)
        self.assertNotIn("target.password", script)

    def test_deployment_admin_get_routes_require_basic_auth(self):
        source = (ROOT / "admin_server.py").read_text(encoding="utf-8")
        for route in (
            "/api/admin/deployment/status",
            "/api/admin/deployment/job",
        ):
            start = source.index("if path=='" + route + "':")
            block = source[start:start + 350]
            self.assertIn("if not self.authorized(): return self.require_auth()", block)

    def test_deployment_mutations_live_after_admin_origin_guard(self):
        source = (ROOT / "admin_server.py").read_text(encoding="utf-8")
        post = source.index(" def do_POST(self):")
        delete = source.index(" def do_DELETE(self):", post)
        post_source = source[post:delete]
        guard = post_source.index("if path.startswith('/api/admin/'):")
        origin = post_source.index("if not self._admin_origin_ok()", guard)
        for route in (
            "/api/admin/deployment/target",
            "/api/admin/deployment/hostkey/scan",
            "/api/admin/deployment/hostkey/trust",
            "/api/admin/deployment/probe",
            "/api/admin/deployment/plan",
            "/api/admin/deployment/update-status",
            "/api/admin/deployment/job",
        ):
            self.assertGreater(
                post_source.index("if path=='" + route + "':"),
                origin,
            )

    def test_update_ui_exposes_remote_version_and_check_button(self):
        html = (ROOT / "admin" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="deploymentSourceState"', html)
        self.assertIn('id="deploymentRemoteSha"', html)
        self.assertIn('id="deploymentUpdateState"', html)
        self.assertIn('id="deploymentCheckUpdate"', html)
        self.assertIn('id="deploymentRollbackCandidates"', html)

    def test_packaged_source_ui_disables_install_and_update(self):
        script = (ROOT / "admin" / "deployment.js").read_text(encoding="utf-8")
        self.assertIn("$('deploymentInstall').disabled = !sourceBuildCapable()", script)
        self.assertIn(
            "$('deploymentUpdate').disabled = !updateState.updateAvailable || !sourceBuildCapable()",
            script,
        )
        self.assertIn("Source Git de build indisponible", script)

    def test_security_ci_checks_deployment_javascript(self):
        workflow = (ROOT / ".github" / "workflows" / "security-ci.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("node --check admin/deployment.js", workflow)


if __name__ == "__main__":
    unittest.main()
