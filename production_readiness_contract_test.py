import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class ProductionReadinessContractTest(unittest.TestCase):
    def test_admin_exposes_readiness_endpoint_and_panel(self):
        server = (ROOT / "admin_server.py").read_text()
        html = (ROOT / "admin" / "index.html").read_text()
        javascript = (ROOT / "admin" / "readiness.js").read_text()
        self.assertIn("/api/admin/readiness", server)
        route_start = server.index("if path=='/api/admin/readiness'")
        route_end = server.index("if path=='/api/admin/integrations/google/status'", route_start)
        self.assertIn("self.authorized()", server[route_start:route_end])
        self.assertIn('id="readiness"', html)
        self.assertIn('id="readinessComponents"', html)
        self.assertIn("/api/admin/readiness", javascript)

    def test_readiness_renderer_uses_safe_dom(self):
        javascript = (ROOT / "admin" / "readiness.js").read_text()
        start = javascript.index("function renderReadinessComponents")
        end = javascript.index("async function loadProductionReadiness", start)
        renderer = javascript[start:end]
        self.assertIn("textContent", renderer)
        self.assertIn("replaceChildren", renderer)
        self.assertNotIn("innerHTML", renderer)

    def test_ci_checks_readiness_javascript(self):
        workflow = (ROOT / ".github" / "workflows" / "security-ci.yml").read_text()
        self.assertIn("node --check admin/readiness.js", workflow)


if __name__ == "__main__":
    unittest.main()
