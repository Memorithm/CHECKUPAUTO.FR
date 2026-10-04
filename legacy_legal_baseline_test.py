import tempfile
import unittest
from pathlib import Path

import compliance_store
import legacy_legal_baseline


class LegacyLegalBaselineTest(unittest.TestCase):
    def test_all_five_legacy_documents_are_available_with_provenance(self):
        docs = legacy_legal_baseline.all_documents()
        self.assertEqual(set(docs), set(compliance_store.DOCUMENT_TYPES))
        for kind, row in docs.items():
            with self.subTest(kind=kind):
                self.assertTrue(row["legacyBaseline"])
                self.assertEqual(row["status"], "legacy_baseline")
                self.assertEqual(row["legacyCapturedAt"], "2026-10-04")
                self.assertTrue(row["legacySources"])
                self.assertTrue(all(x.startswith("https://rdv.checkupauto.fr/") for x in row["legacySources"]))
                self.assertGreater(len(row["body"]), 80)
                self.assertEqual(len(row["contentHash"]), 64)

    def test_center_identity_is_preserved_from_active_legal_notice(self):
        body = legacy_legal_baseline.document("legal_notice")["body"]
        self.assertIn("CHECK UP AUTO", body)
        self.assertIn("Agrément : S078Z206", body)
        self.assertIn("SIRET : 811 945 435 00022", body)
        self.assertIn("N° intracommunautaire : FR59811945435", body)
        self.assertIn("Capital social : 10000 €", body)
        self.assertIn("AutoBilan-Systems", body)
        self.assertIn("KALANDA", body)

    def test_active_privacy_and_rgpd_text_are_both_preserved(self):
        body = legacy_legal_baseline.document("privacy")["body"]
        self.assertIn("Politiques de Confidentialités", body)
        self.assertIn("Politique RGPD", body)
        self.assertIn("AutoBilan-Systems", body)
        self.assertIn("droit d’accès, de rectification, de limitation, d’effacement", body)
        self.assertIn("contact@autobilan-systems.com", body)

    def test_active_cookie_policy_is_preserved(self):
        body = legacy_legal_baseline.document("cookies")["body"]
        self.assertIn("Cookies et technologies similaires", body)
        self.assertIn("Google Analytics", body)
        self.assertIn("24 mois", body)
        self.assertIn("CNIL", body)

    def test_active_mercureweb_terms_are_preserved(self):
        row = legacy_legal_baseline.document("terms")
        self.assertEqual(row["version"], "mercureweb-2022-legacy")
        self.assertIn("Conditions Générales de Vente MercureWeb – AutoBilan-Systems - version 2022", row["body"])
        self.assertIn("DROIT DE RÉTRACTATION LÉGAL", row["body"])
        self.assertIn("11. RÉCLAMATION", row["body"])
        self.assertIn("D24VL G", row["body"])

    def test_withdrawal_baseline_is_exactly_sourced_from_active_terms(self):
        withdrawal = legacy_legal_baseline.document("withdrawal")
        terms = legacy_legal_baseline.document("terms")
        self.assertIn("DROIT DE RÉTRACTATION LÉGAL", withdrawal["body"])
        self.assertIn("14 jours ouvrés", withdrawal["body"])
        self.assertIn("formulaire de Contact", withdrawal["body"])
        self.assertIn(withdrawal["body"].replace("DROIT DE RÉTRACTATION LÉGAL : ", "").strip(), terms["body"])

    def test_missing_runtime_document_falls_back_without_persisting_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "compliance.sqlite3"
            row = compliance_store.public_document_for_path("/confidentialite", db)
            self.assertTrue(row["legacyBaseline"])
            self.assertEqual(compliance_store.documents(db), [])
            state = compliance_store.summary(db)
            self.assertIn("privacy", state["missingDocuments"])
            self.assertFalse(state["readyForPublicContracting"])

    def test_test_only_runtime_document_does_not_override_legacy_baseline_or_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "compliance.sqlite3"
            compliance_store.save_document({
                "type": "terms",
                "version": "test-2026-10-01",
                "title": "CGV provisoires — TEST uniquement",
                "body": "CGV DE SUBSTITUTION — ENVIRONNEMENT DE TEST UNIQUEMENT. " + ("Essai technique. " * 8),
                "action": "publish",
            }, db)
            public = compliance_store.public_document_for_path("/cgv", db)
            self.assertTrue(public["legacyBaseline"])
            self.assertEqual(public["version"], "mercureweb-2022-legacy")
            state = compliance_store.summary(db)
            self.assertIn("terms", state["missingDocuments"])
            self.assertEqual(state["publishedDocuments"], 0)
            self.assertFalse(state["readyForPublicContracting"])

    def test_real_runtime_publication_overrides_legacy_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "compliance.sqlite3"
            current = compliance_store.save_document({
                "type": "privacy",
                "version": "2026.10.04",
                "title": "Politique de confidentialité",
                "body": "Politique approuvée et publiée dans le registre runtime. " + ("Contenu contrôlé. " * 8),
                "action": "publish",
            }, db)
            public = compliance_store.public_document_for_path("/confidentialite", db)
            self.assertFalse(public.get("legacyBaseline", False))
            self.assertEqual(public["contentHash"], current["contentHash"])
            self.assertEqual(public["version"], "2026.10.04")

    def test_placeholder_marker_is_fail_closed(self):
        samples = [
            {"version": "draft-1", "title": "CGV", "body": "x"},
            {"version": "v1", "title": "CGV provisoires", "body": "x"},
            {"version": "v1", "title": "CGV", "body": "Document juridique non publié"},
        ]
        for row in samples:
            with self.subTest(row=row):
                self.assertTrue(compliance_store._test_or_placeholder_document(row))

    def test_admin_renderer_marks_legacy_provenance(self):
        source = (Path(__file__).resolve().parent / "admin_server.py").read_text(encoding="utf-8")
        self.assertIn("Baseline repris du site de réservation actif", source)
        self.assertIn("legacyCapturedAt", source)
        self.assertIn("legacySources", source)


if __name__ == "__main__":
    unittest.main()
