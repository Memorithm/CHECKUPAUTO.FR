"""Stage visual-preview tests; no Mercure account or writes required."""
import datetime as dt
import unittest
from pathlib import Path
from unittest.mock import patch

import booking_promo_preview as preview


ENV = {
    "CYBERCHECK_RUNTIME_ENV": "staging",
    "CYBERCHECK_PROMO_PREVIEW": "1",
    "CYBERCHECK_STAGING_HOST": "stage.179.198.210.187.sslip.io",
    "CYBERCHECK_LOW_DEMAND_PROMO_PUBLISH": "0",
}
HOST = ENV["CYBERCHECK_STAGING_HOST"]


class PromoPreviewTest(unittest.TestCase):
    def test_exactly_four_october_week_slots_with_five_euro_saving(self):
        for service, original in (("technical", 80.0), ("fitted", 90.0)):
            with self.subTest(service=service):
                data = preview.build(service, {"enabled": True})
                slots = [(day["date"], slot) for day in data["days"]
                         for slot in day["slots"]]
                self.assertEqual(len(slots), 4)
                self.assertEqual([d for d, _ in slots], [
                    "2026-10-09", "2026-10-09",
                    "2026-10-10", "2026-10-10"])
                for _, slot in slots:
                    self.assertTrue(slot["previewOnly"])
                    self.assertTrue(slot["promotion"])
                    self.assertEqual(slot["basePrice"], original)
                    self.assertEqual(slot["price"], original - 5)
                    self.assertEqual(slot["saving"], 5.0)
                    self.assertEqual(slot["lowDemandOffer"]["savingEuro"], 5.0)
                self.assertFalse(data["preview"]["bookable"])
                self.assertFalse(data["preview"]["providerPriceVerified"])
                self.assertEqual(data["preview"]["expiresAt"], "2026-10-11")

    def test_exact_stage_host_and_two_environment_guards(self):
        date = dt.date(2026, 10, 8)
        self.assertTrue(preview.enabled(HOST, environ=ENV, today=date))
        self.assertTrue(preview.enabled(HOST + ":443", environ=ENV, today=date))
        self.assertFalse(preview.enabled("www.checkupauto.fr", environ=ENV, today=date))
        self.assertFalse(preview.enabled("test.checkupauto.fr", environ=ENV, today=date))
        self.assertFalse(preview.enabled("", environ=ENV, today=date))
        self.assertFalse(preview.enabled(HOST, environ={**ENV, "CYBERCHECK_RUNTIME_ENV": "production"}, today=date))
        self.assertFalse(preview.enabled(HOST, environ={**ENV, "CYBERCHECK_PROMO_PREVIEW": "0"}, today=date))
        self.assertFalse(preview.enabled(HOST, environ={**ENV, "CYBERCHECK_LOW_DEMAND_PROMO_PUBLISH": "1"}, today=date))

    def test_week_boundaries_expire_automatically(self):
        self.assertFalse(preview.enabled(HOST, environ=ENV, today=dt.date(2026, 10, 7)))
        self.assertTrue(preview.enabled(HOST, environ=ENV, today=dt.date(2026, 10, 11)))
        self.assertFalse(preview.enabled(HOST, environ=ENV, today=dt.date(2026, 10, 12)))

    def test_preview_never_reads_live_availability_or_publishes_offer(self):
        with patch.object(preview.mercure_public, "availability", side_effect=AssertionError("live availability")), \
             patch("mercure_admin_client.plan_promotion_slot", side_effect=AssertionError("provider mutation")):
            data = preview.build("technical", {"enabled": True})
        self.assertEqual(data["preview"]["slotCount"], 4)

    def test_invalid_service_is_rejected_without_fabricating_rates(self):
        with self.assertRaises(ValueError):
            preview.build("pollution", {})

    def test_preview_server_and_browser_enforce_nonbooking_boundary(self):
        root = Path(__file__).parent
        server = (root / "admin_server.py").read_text(encoding="utf-8")
        browser = (root / "app.js").read_text(encoding="utf-8")
        compose = (root / "deploy/hostinger/docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("booking_promo_preview.enabled(self.headers.get('Host',''))", server)
        self.assertIn("booking_promo_preview.build(", server)
        self.assertIn("promoPreviewAllowed", server)
        self.assertIn("promoPreviewActive()", browser)
        self.assertIn("slot.previewOnly && promoPreviewActive()", browser)
        self.assertIn("Aperçu uniquement", browser)
        self.assertIn('CYBERCHECK_RUNTIME_ENV: "staging"', compose)
        self.assertIn('CYBERCHECK_PROMO_PREVIEW: "1"', compose)


if __name__ == "__main__":
    unittest.main()
