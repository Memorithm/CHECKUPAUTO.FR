import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import compliance_store
import legacy_legal_baseline


ROOT = Path(__file__).resolve().parent
CLI = ROOT / "scripts" / "checkupauto-compliance-ops.py"


class LegacyLegalPublicationTest(unittest.TestCase):
    def test_blank_store_publishes_all_five_baselines_without_claiming_global_readiness(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "compliance.sqlite3"
            result = legacy_legal_baseline.publish_to_store(db)
            self.assertEqual(result["publishedDocuments"], 5)
            self.assertEqual(result["requiredDocuments"], 5)
            self.assertEqual(result["missingDocuments"], [])
            self.assertFalse(result["readyForPublicContracting"])
            self.assertFalse(result["legalConformityAttested"])
            self.assertEqual(
                [row["action"] for row in result["results"]],
                ["published_legacy_baseline"] * 5,
            )
            for row in result["results"]:
                self.assertNotIn("body", row)

    def test_test_only_terms_are_retired_and_replaced_by_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "compliance.sqlite3"
            compliance_store.save_document({
                "type": "terms",
                "version": "test-2026-10-01",
                "title": "CGV provisoires — TEST uniquement",
                "body": "CGV DE SUBSTITUTION — ENVIRONNEMENT DE TEST UNIQUEMENT. " + ("Essai technique. " * 8),
                "action": "publish",
            }, db)
            legacy_legal_baseline.publish_to_store(db)
            current = compliance_store.published_document("terms", db)
            self.assertEqual(current["version"], "mercureweb-2022-legacy")
            history = [row for row in compliance_store.documents(db) if row["type"] == "terms"]
            states = {row["version"]: row["status"] for row in history}
            self.assertEqual(states["test-2026-10-01"], "retired")
            self.assertEqual(states["mercureweb-2022-legacy"], "published")

    def test_real_runtime_publication_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "compliance.sqlite3"
            real = compliance_store.save_document({
                "type": "privacy",
                "version": "2026.10.04",
                "title": "Politique de confidentialité",
                "body": "Document runtime explicitement publié et revu. " + ("Contenu de production. " * 8),
                "action": "publish",
            }, db)
            result = legacy_legal_baseline.publish_to_store(db)
            current = compliance_store.published_document("privacy", db)
            self.assertEqual(current["version"], "2026.10.04")
            self.assertEqual(current["contentHash"], real["contentHash"])
            action = next(x["action"] for x in result["results"] if x["type"] == "privacy")
            self.assertEqual(action, "preserved_current_publication")

    def test_publication_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "compliance.sqlite3"
            first = legacy_legal_baseline.publish_to_store(db)
            second = legacy_legal_baseline.publish_to_store(db)
            self.assertEqual(first["publishedDocuments"], 5)
            self.assertEqual(second["publishedDocuments"], 5)
            self.assertTrue(all(x["action"] == "already_current" for x in second["results"]))
            self.assertEqual(len(compliance_store.documents(db)), 5)

    def test_cli_requires_explicit_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "compliance.sqlite3"
            bad = subprocess.run(
                [sys.executable, str(CLI), "--db", str(db), "publish-legacy-legal-baseline", "--confirm", "NO"],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(bad.returncode, 0)
            self.assertIn("PUBLISH-LEGACY-RDV-BASELINE", bad.stderr)

    def test_cli_publishes_metadata_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "compliance.sqlite3"
            good = subprocess.run(
                [sys.executable, str(CLI), "--db", str(db), "publish-legacy-legal-baseline", "--confirm", "PUBLISH-LEGACY-RDV-BASELINE"],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=True,
            )
            payload = json.loads(good.stdout)
            self.assertEqual(payload["publishedDocuments"], 5)
            self.assertFalse(payload["readyForPublicContracting"])
            self.assertNotIn("body", good.stdout)
            self.assertNotIn("Conditions Générales de Vente MercureWeb", good.stdout)


if __name__ == "__main__":
    unittest.main()
