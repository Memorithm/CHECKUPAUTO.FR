import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class NotificationAdminContractTest(unittest.TestCase):
    def test_admin_exposes_permanent_failure_metric_and_transport_health(self):
        html = (ROOT / "admin" / "index.html").read_text()
        javascript = (ROOT / "admin" / "notifications.js").read_text()
        self.assertIn('id="notificationPermanent"', html)
        self.assertIn('id="notificationTransportHealth"', html)
        self.assertIn("resilience.permanentFailures", javascript)
        self.assertIn("renderTransportHealth(transportHealth)", javascript)

    def test_transport_health_renderer_uses_text_content(self):
        javascript = (ROOT / "admin" / "notifications.js").read_text()
        start = javascript.index("function renderTransportHealth")
        end = javascript.index("function renderNotificationRows", start)
        renderer = javascript[start:end]
        self.assertIn("notificationCell", renderer)
        self.assertNotIn("innerHTML", renderer)

    def test_admin_exposes_non_delivering_transport_preflight(self):
        html = (ROOT / "admin" / "index.html").read_text()
        javascript = (ROOT / "admin" / "notifications.js").read_text()
        server = (ROOT / "admin_server.py").read_text()
        self.assertIn('id="notificationPreflight"', html)
        self.assertIn('id="notificationPreflightRows"', html)
        self.assertIn("/api/admin/notifications/preflight", javascript)
        self.assertIn("/api/admin/notifications/preflight", server)

    def test_preflight_renderer_uses_text_content(self):
        javascript = (ROOT / "admin" / "notifications.js").read_text()
        start = javascript.index("function renderPreflight")
        end = javascript.index("function renderNotificationRows", start)
        renderer = javascript[start:end]
        self.assertIn("notificationCell", renderer)
        self.assertNotIn("innerHTML", renderer)


if __name__ == "__main__":
    unittest.main()
