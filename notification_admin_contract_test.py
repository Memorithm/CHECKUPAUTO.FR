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

    def test_admin_exposes_governed_permanent_failure_lifecycle(self):
        html = (ROOT / "admin" / "index.html").read_text()
        javascript = (ROOT / "admin" / "notifications.js").read_text()
        server = (ROOT / "admin_server.py").read_text()
        self.assertIn('id="notificationPermanentAcknowledged"', html)
        self.assertIn('id="notificationPermanentResolved"', html)
        self.assertIn('id="notificationPermanentRows"', html)
        self.assertIn("/api/admin/notifications/permanent/action", javascript)
        self.assertIn("/api/admin/notifications/permanent/action", server)
        start = javascript.index("function renderPermanentFailures")
        end = javascript.index("async function loadNotificationStatus", start)
        renderer = javascript[start:end]
        self.assertIn("textContent", renderer)
        self.assertNotIn("innerHTML", renderer)

    def test_admin_exposes_privacy_safe_recipient_reconciliation(self):
        html = (ROOT / "admin" / "index.html").read_text()
        javascript = (ROOT / "admin" / "notifications.js").read_text()
        server = (ROOT / "admin_server.py").read_text()
        self.assertIn("Destinataire Mercure", html)
        self.assertIn("/api/admin/notifications/permanent/recipient-check", javascript)
        self.assertIn("/api/admin/notifications/permanent/retry", javascript)
        self.assertIn("/api/admin/notifications/permanent/recipient-check", server)
        self.assertIn("/api/admin/notifications/permanent/retry", server)
        self.assertIn("item.recipient_check_state", javascript)
        self.assertIn("item.recipient_checked_at", javascript)
        self.assertNotIn("recipient_hash", javascript)
        self.assertNotIn("recipient_hash", html)

    def test_admin_exposes_reminder_permanent_suppression_metric(self):
        html = (ROOT / "admin" / "index.html").read_text()
        javascript = (ROOT / "admin" / "notifications.js").read_text()
        self.assertIn('id="notificationReminderPermanentSuppressed"', html)
        self.assertIn("reminder.lastProcess?.permanentSuppressed", javascript)

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

    def test_admin_exposes_ios_distribution_channel(self):
        html = (ROOT / "admin" / "index.html").read_text()
        javascript = (ROOT / "admin" / "notifications.js").read_text()
        self.assertIn('id="notificationAppDistribution"', html)
        self.assertIn("/api/app/status", javascript)
        self.assertIn("distributionChannel==='testflight'", javascript)
        self.assertIn("distributionChannel==='app-store'", javascript)

    def test_admin_claim_qr_uses_privileged_endpoints_and_safe_dom(self):
        html = (ROOT / "admin" / "index.html").read_text()
        javascript = (ROOT / "admin" / "notifications.js").read_text()
        self.assertIn('id="notificationClaimDelivery"', html)
        self.assertIn('id="claimVehicleSelect"', html)
        self.assertIn('id="claimQrImage"', html)
        self.assertIn("/api/admin/mobile/claims/candidates?limit=30", javascript)
        self.assertIn("/api/admin/mobile/claims/issue", javascript)
        start = javascript.index("function renderClaimCandidates")
        end = javascript.index("async function runNotificationPreflight", start)
        renderer = javascript[start:end]
        self.assertIn("textContent", renderer)
        self.assertNotIn("innerHTML", renderer)
        self.assertNotIn("claimUrl", javascript)

    def test_preflight_renderer_uses_text_content(self):
        javascript = (ROOT / "admin" / "notifications.js").read_text()
        start = javascript.index("function renderPreflight")
        end = javascript.index("function renderNotificationRows", start)
        renderer = javascript[start:end]
        self.assertIn("notificationCell", renderer)
        self.assertNotIn("innerHTML", renderer)


if __name__ == "__main__":
    unittest.main()
