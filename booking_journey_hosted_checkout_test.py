import json
import shutil
import subprocess
import tempfile
import unittest
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
    def test_checkout_mode_is_validated(self):
        with self.assertRaises(ValueError):
            in_site_booking_page.render_summary(
                token="t", service_label="x", service_key="technical", nonce="n", vehicle={},
                account={}, csrf="c", business={}, checkout_mode="other")


if __name__ == "__main__":
    unittest.main()
