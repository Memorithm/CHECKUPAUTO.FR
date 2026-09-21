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
        self.assertNotIn("credential.password", script)
        self.assertNotIn("target.password", script)

    def test_deployment_ui_surfaces_pending_dns_cutover(self):
        script = (ROOT / "admin" / "deployment.js").read_text(encoding="utf-8")
        self.assertIn("waiting_external", script)
        self.assertIn("Bascule DNS/SSL requise", script)

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
            "/api/admin/deployment/job",
        ):
            self.assertGreater(
                post_source.index("if path=='" + route + "':"),
                origin,
            )

    def test_security_ci_checks_deployment_javascript(self):
        workflow = (ROOT / ".github" / "workflows" / "security-ci.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("node --check admin/deployment.js", workflow)


if __name__ == "__main__":
    unittest.main()
