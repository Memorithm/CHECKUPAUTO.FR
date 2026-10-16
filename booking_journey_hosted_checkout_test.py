import json
from contextlib import ExitStack
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import in_site_booking_page

ROOT = Path(__file__).resolve().parent

HARNESS = r"""
const api = require(process.argv[2]);
const out = {};
function response(status, body) { return { status, json: async () => body }; }
(async () => {
  out.redirect = api.classifyHostedStart(200, { ok: true, redirectUrl: 'https://webpayment.payline.com/v2/?token=x',
    statusPollSeconds: 5, statusPollMaxSeconds: 1200 });
  out.uncertain = api.classifyHostedStart(503, { ok: false, error: 'mercure_checkout_response_uncertain' });
  out.network = api.classifyHostedStart(0, null);
  out.replayed = api.classifyHostedStart(409, { ok: false, error: 'booking_reconciliation_required' });
  out.disabled = api.classifyHostedStart(503, { ok: false, error: 'mercure_hosted_payment_disabled' });
  out.slot = api.classifyHostedStart(422, { ok: false, error: 'booking_slot_unavailable' });
  out.energy = api.classifyHostedStart(422, { ok: false, error: 'booking_vehicle_energy_not_offered' });
  out.httpUrl = api.classifyHostedStart(200, { ok: true, redirectUrl: 'http://x' });

  const data = { service: 'technical', date: '2026-10-20', time: '09:00', vehicleId: 'v', csrf: 'c', ccid: 'i', cct: 't',
    termsVersion: '1', termsContentHash: 'h', requiresImmediatePerformance: false };
  const seq = [
    response(200, { ok: true, state: 'payment_pending', confirmed: false }),
    response(200, { ok: true, state: 'payment_pending', confirmed: false }),
    response(200, { ok: true, state: 'confirmed', confirmed: true, paid: true })
  ];
  const calls = [];
  const fetchImpl = async (url, opts) => { calls.push([url, JSON.parse(opts.body)]); return seq.shift(); };
  out.paid = await api.waitHostedPayment({ fetchImpl, data, requestKey: 'k'.repeat(24), pollMs: 5000, maxMs: 60000, sleep: async () => {} });
  out.paidCalls = calls.length;
  out.statusBody = calls[0][1];
  out.statusUrl = calls[0][0];

  const cancelled = await api.waitHostedPayment({ fetchImpl: async () => response(200, { ok: true, state: 'payment_cancelled' }),
    data, requestKey: 'k'.repeat(24), pollMs: 5000, maxMs: 60000, sleep: async () => {} });
  out.cancelled = cancelled.state;
  let ticks = 0;
  const timeout = await api.waitHostedPayment({ fetchImpl: async () => response(200, { ok: true, state: 'payment_pending' }),
    data, requestKey: 'k'.repeat(24), pollMs: 5000, maxMs: 20000, sleep: async () => {}, onTick: () => { ticks += 1; } });
  out.timeout = timeout.state; out.ticks = ticks;

  const startCalls = [];
  const started = await api.startHostedCheckout({ data, requestKey: 'k'.repeat(24), immediate: false,
    fetchImpl: async (url, opts) => { startCalls.push(url); return url === api.ROUTES.acceptTerms
      ? response(201, { ok: true })
      : response(200, { ok: true, redirectUrl: 'https://webpayment.payline.com/v2/?token=y' }); } });
  out.started = started.state; out.startCalls = startCalls;
  process.stdout.write(JSON.stringify(out));
})();
"""


@unittest.skipUnless(shutil.which("node"), "node requis")
class HostedCheckoutJourneyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "harness.js"
            script.write_text(HARNESS, encoding="utf-8")
            result = subprocess.run(["node", str(script), str(ROOT / "assets" / "booking-journey.js")],
                                    capture_output=True, text=True, timeout=30, check=True)
        cls.r = json.loads(result.stdout)

    def test_start_outcomes(self):
        self.assertEqual(self.r["redirect"]["state"], "redirect")
        self.assertEqual(self.r["redirect"]["maxMs"], 1200000)
        # An uncertain answer may have created the appointment: verify, never fall back.
        for name in ("uncertain", "network", "replayed"):
            self.assertEqual(self.r[name]["state"], "verify", name)
        self.assertEqual(self.r["disabled"]["state"], "fallback")
        self.assertEqual(self.r["slot"]["state"], "slot_lost")
        self.assertEqual(self.r["energy"]["state"], "vehicle")
        self.assertEqual(self.r["httpUrl"]["state"], "verify")

    def test_waits_for_payment_then_stops(self):
        self.assertEqual(self.r["paid"], {"state": "confirmed"})
        self.assertEqual(self.r["paidCalls"], 3)
        self.assertEqual(self.r["statusUrl"], "/api/customer/booking/mercure-checkout/status")
        self.assertEqual(set(self.r["statusBody"]), {"service", "date", "time", "vehicleId", "requestKey"})
        self.assertEqual(self.r["cancelled"], "cancelled")
        self.assertEqual(self.r["timeout"], "timeout")
        self.assertEqual(self.r["ticks"], 5)

    def test_consent_is_recorded_before_the_booking_call(self):
        self.assertEqual(self.r["started"], "redirect")
        self.assertEqual(self.r["startCalls"], ["/api/booking/accept-terms", "/api/customer/booking/mercure-checkout"])


class HostedSummaryPageTest(unittest.TestCase):
    @staticmethod
    def _summary(mode: str) -> str:
        with ExitStack() as stack:
            booking = in_site_booking_page.booking
            for method, value in (
                ("mercure_prestation", "Contrôle technique"),
                ("require_published_terms", {"version": "2026-10", "contentHash": "hash"}),
                ("browser_token", "signed-browser-token"),
                ("_checkout_requirements", {
                    "preferredDate": "2026-10-20", "preferredTime": "09:00",
                    "requiresImmediatePerformance": False,
                }),
                ("preferred_mercure_quote", {"price": 72}),
            ):
                stack.enter_context(patch.object(booking, method, return_value=value))
            stack.enter_context(patch.object(in_site_booking_page.mercure_public_client,
                                             "SERVICES", {"technical": "Contrôle technique"}))
            return in_site_booking_page.render_summary(
                token="intent-token", service_label="Contrôle technique", service_key="technical",
                nonce="test-nonce", vehicle={"vehicleId": "vehicle-1"},
                account={"billingContactComplete": True, "email": "client@example.com"},
                csrf="csrf", business={}, checkout_mode=mode,
            ).decode("utf-8")

    def test_payline_return_warning_is_visible_before_checkout_and_during_wait(self):
        html = self._summary("mercure-hosted")
        self.assertIn("IMPORTANT : ne fermez pas cette fenêtre", html)
        self.assertIn("Gardez cette page CHECKUPAUTO ouverte.", html)
        self.assertIn("revenez sur cette page pour vérifier", html)
        self.assertIn("que votre réservation a bien été prise en compte par le centre.", html)
        self.assertIn('aria-labelledby="bjReturnNoticeTitle"', html)
        self.assertIn('aria-labelledby="bjReturnWaitTitle"', html)
        self.assertIn('aria-hidden="true">!</span>', html)
        self.assertEqual(html.count('<aside class="bj-return-notice'), 2)
        self.assertLess(html.index('id="bjReturnNoticeTitle"'), html.index('id="bjConfirm"'))
        self.assertLess(html.index('id="bjHostedWait"'), html.index('id="bjReturnWaitTitle"'))
        self.assertIn("booking-journey.css?v=20261016-2", html)

    def test_no_payline_other_tab_warning_for_same_tab_site_mode(self):
        html = self._summary("site")
        self.assertNotIn("bj-return-notice", html)
        self.assertNotIn("bjReturnWaitTitle", html)

    def test_warning_animation_is_optional_and_accessible(self):
        css = (ROOT / "assets" / "booking-journey.css").read_text(encoding="utf-8")
        self.assertIn("@keyframes bj-return-halo", css)
        self.assertIn("@keyframes bj-return-flash", css)
        self.assertIn("animation:bj-return-flash", css)
        self.assertIn("@media (prefers-reduced-motion:reduce)", css)
        reduced = css.split("@media (prefers-reduced-motion:reduce)", 1)[1]
        self.assertIn(".bj .bj-return-notice{animation:none", reduced)
        self.assertIn(".bj .bj-return-notice__badge{animation:none}", reduced)

    def test_checkout_mode_is_validated(self):
        with self.assertRaises(ValueError):
            in_site_booking_page.render_summary(
                token="t", service_label="x", service_key="technical", nonce="n", vehicle={},
                account={}, csrf="c", business={}, checkout_mode="other")


if __name__ == "__main__":
    unittest.main()
