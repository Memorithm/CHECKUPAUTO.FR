import hashlib
import json
import unittest
from pathlib import Path

import legacy_legal_baseline


ROOT = Path(__file__).resolve().parent


class CurrentSiteLegalAddendaTest(unittest.TestCase):
    def test_addenda_exist_only_for_legal_privacy_and_cookies(self):
        self.assertIsNotNone(legacy_legal_baseline.current_scope_addendum("legal_notice"))
        self.assertIsNotNone(legacy_legal_baseline.current_scope_addendum("privacy"))
        self.assertIsNotNone(legacy_legal_baseline.current_scope_addendum("cookies"))
        self.assertIsNone(legacy_legal_baseline.current_scope_addendum("terms"))
        self.assertIsNone(legacy_legal_baseline.current_scope_addendum("withdrawal"))

    def test_legacy_baseline_content_hash_is_not_changed_by_addendum(self):
        manifest = json.loads((ROOT / "legal/legacy-rdv/manifest.json").read_text(encoding="utf-8"))
        for kind in ("legal_notice", "privacy", "cookies"):
            rel = manifest["documents"][kind]["file"]
            raw = (ROOT / rel).read_text(encoding="utf-8")
            expected = hashlib.sha256(legacy_legal_baseline._plain(raw).encode("utf-8")).hexdigest()
            row = legacy_legal_baseline.document(kind)
            self.assertEqual(row["contentHash"], expected)

    def test_new_site_identity_addendum_is_factual_and_does_not_claim_mediator(self):
        body = legacy_legal_baseline.current_scope_addendum("legal_notice")["body"]
        self.assertIn("CHECK UP AUTO", body)
        self.assertIn("811 945 435", body)
        self.assertIn("1 rue Niépce", body)
        self.assertIn("Tarek Zekriti", body)
        self.assertIn("PlanetHoster", body)
        self.assertIn("ne vaut pas attestation d’un médiateur", body)

    def test_privacy_addendum_describes_actual_federated_and_ios_boundaries(self):
        body = legacy_legal_baseline.current_scope_addendum("privacy")["body"]
        self.assertIn("Apple ou Google", body)
        self.assertIn("ne demande ni ne stocke le mot de passe Apple ou Google", body)
        self.assertIn("trousseau iOS", body)
        self.assertIn("cookie Secure et HttpOnly", body)
        self.assertIn("cookieless", body)
        self.assertIn("180 jours", body)
        self.assertIn("ne sont considérés comme attestés", body)

    def test_cookie_addendum_distinguishes_legacy_google_analytics_from_new_site(self):
        body = legacy_legal_baseline.current_scope_addendum("cookies")["body"]
        self.assertIn("Google Analytics", body)
        self.assertIn("service rdv.checkupauto.fr", body)
        self.assertIn("mode cookieless", body)
        self.assertIn("180 jours", body)

    def test_renderer_keeps_legacy_and_current_scope_visually_separate(self):
        source = (ROOT / "admin_server.py").read_text(encoding="utf-8")
        self.assertIn("Continuité documentaire.", source)
        self.assertIn("Complément nouveau site / application", source)
        self.assertIn("current_scope_addendum", source)
        self.assertIn("version.startswith('legacy-rdv-')", source)
        self.assertIn("version.startswith('mercureweb-2022-legacy')", source)


if __name__ == "__main__":
    unittest.main()
