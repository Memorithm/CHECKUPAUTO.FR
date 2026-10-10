"""S-13: Mercure webhook freshness/anti-replay and one synthetic conversion per intent."""
import hashlib
import hmac
import json
import os
import time
import unittest
from unittest import mock

import analytics_store as analytics
import booking_bridge as booking
import booking_contract_acceptance_test as _bca


class _BookingStore(unittest.TestCase):
    # Reuse the isolated store fixture without re-running its tests.
    setUp = _bca.BookingContractAcceptanceTest.setUp
    tearDown = _bca.BookingContractAcceptanceTest.tearDown
    intent = _bca.BookingContractAcceptanceTest.intent
    acceptance_payload = _bca.BookingContractAcceptanceTest.acceptance_payload


class SyntheticConversionTest(_BookingStore):
    def test_varying_route_does_not_create_more_synthetic_conversions(self):
        intent = self.intent()
        booking.record_terms_acceptance(self.acceptance_payload(intent))
        ids = set()
        for route in ("/confirmation", "/confirmation?x=1", "/autre"):
            ids.add(booking.browser_confirmation({"ccid": intent["token"], "cct": booking.browser_token(intent["token"]), "route": route})["externalId"])
        self.assertEqual(len(ids), 1)
        with analytics.connect() as db:
            count = db.execute("SELECT COUNT(*) FROM booking_conversions WHERE external_id LIKE 'browser-%'").fetchone()[0]
        self.assertEqual(count, 1)


class WebhookVerificationTest(_BookingStore):
    def sign(self, raw, stamp=None):
        material = (stamp.encode() + b"." + raw) if stamp else raw
        return "sha256=" + hmac.new(booking.ensure_secret().encode(), material, hashlib.sha256).hexdigest()

    def test_timestamped_signature_within_window_is_accepted(self):
        raw = b'{"externalId":"x"}'; stamp = str(int(time.time()))
        self.assertTrue(booking.verify_webhook(raw, self.sign(raw, stamp), stamp))

    def test_stale_timestamp_is_refused(self):
        raw = b'{"externalId":"x"}'; stamp = str(int(time.time()) - 3600)
        self.assertFalse(booking.verify_webhook(raw, self.sign(raw, stamp), stamp))

    def test_timestamp_cannot_be_swapped(self):
        raw = b'{"externalId":"x"}'; stamp = str(int(time.time()))
        self.assertFalse(booking.verify_webhook(raw, self.sign(raw, stamp), str(int(stamp) + 1)))

    def test_legacy_body_signature_refused_when_timestamp_required(self):
        raw = b'{"externalId":"x"}'
        self.assertTrue(booking.verify_webhook(raw, self.sign(raw)))
        with mock.patch.dict(os.environ, {booking.WEBHOOK_TIMESTAMP_REQUIRED_ENV: "1"}):
            self.assertFalse(booking.verify_webhook(raw, self.sign(raw)))

    def test_delivery_is_processed_once(self):
        raw = b'{"externalId":"x"}'
        self.assertTrue(booking.remember_webhook(raw, "1"))
        self.assertFalse(booking.remember_webhook(raw, "1"))
        self.assertTrue(booking.remember_webhook(raw, "2"))


class WebhookHttpReplayTest(unittest.TestCase):
    """End-to-end through the real admin Handler."""

    @classmethod
    def setUpClass(cls):
        from admin_http_test_support import AdminHttpHarness
        cls.http = AdminHttpHarness()

    @classmethod
    def tearDownClass(cls):
        cls.http.close()

    def post(self, raw, stamp=None):
        material = (stamp.encode() + b"." + raw) if stamp else raw
        sig = "sha256=" + hmac.new(booking.ensure_secret().encode(), material, hashlib.sha256).hexdigest()
        headers = {"X-CyberCheck-Signature": sig}
        if stamp:
            headers["X-CyberCheck-Timestamp"] = stamp
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.http.server.server_address[1], timeout=10)
        try:
            conn.request("POST", "/api/integrations/mercure/booking-confirmed", body=raw,
                         headers={**headers, "Content-Type": "application/json", "User-Agent": "Mercure-Webhook/1.0"})
            response = conn.getresponse()
            return response.status, json.loads(response.read() or b"null")
        finally:
            conn.close()

    def test_replayed_delivery_is_not_applied_twice(self):
        raw = json.dumps({"externalId": "replay-" + str(time.time_ns()), "status": "completed"}).encode()
        stamp = str(int(time.time()))
        with mock.patch.object(booking, "apply_conversion", return_value={"ok": True}) as apply:
            first = self.post(raw, stamp)
            second = self.post(raw, stamp)
        self.assertEqual(first, (200, {"ok": True}))
        self.assertEqual(second, (200, {"ok": True, "duplicate": True}))
        apply.assert_called_once()

    def test_stale_delivery_is_refused(self):
        raw = b'{"externalId":"stale","status":"confirmed"}'
        with mock.patch.object(booking, "apply_conversion") as apply:
            status, _ = self.post(raw, str(int(time.time()) - 7200))
        self.assertEqual(status, 401)
        apply.assert_not_called()


if __name__ == "__main__":
    unittest.main()
