import tempfile
import unittest
from pathlib import Path

import compliance_store


def payload(version, marker):
    return {
        "type": "terms",
        "version": version,
        "title": "Conditions générales de vente",
        "body": marker + " " + ("Texte contractuel versionné et conservé. " * 8),
        "action": "publish",
    }


class LegalDocumentImmutabilityTest(unittest.TestCase):
    def test_retired_version_remains_immutable_after_new_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "compliance.sqlite3"
            v1 = compliance_store.save_document(payload("2026.1", "Version un."), db)
            v2 = compliance_store.save_document(payload("2026.2", "Version deux."), db)
            rows = {row["version"]: row for row in compliance_store.documents(db)}
            self.assertEqual(rows["2026.1"]["status"], "retired")
            self.assertEqual(rows["2026.2"]["status"], "published")
            original_hash = rows["2026.1"]["contentHash"]
            original_published = rows["2026.1"]["publishedAt"]

            changed = payload("2026.1", "Version un modifiée.")
            changed["action"] = "save"
            with self.assertRaisesRegex(ValueError, "déjà publiée est immuable"):
                compliance_store.save_document(changed, db)

            after = {row["version"]: row for row in compliance_store.documents(db)}
            self.assertEqual(after["2026.1"]["contentHash"], original_hash)
            self.assertEqual(after["2026.1"]["publishedAt"], original_published)
            self.assertEqual(after["2026.1"]["body"], v1["body"])
            self.assertEqual(after["2026.2"]["contentHash"], v2["contentHash"])

    def test_draft_can_still_be_edited_before_first_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "compliance.sqlite3"
            draft = payload("2026.3", "Premier brouillon.")
            draft["action"] = "save"
            first = compliance_store.save_document(draft, db)
            draft["body"] = "Deuxième brouillon. " + ("Texte révisable avant publication. " * 8)
            second = compliance_store.save_document(draft, db)
            self.assertEqual(first["status"], "draft")
            self.assertEqual(second["status"], "draft")
            self.assertNotEqual(first["contentHash"], second["contentHash"])

    def test_published_version_cannot_be_republished_or_rewritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "compliance.sqlite3"
            compliance_store.save_document(payload("2026.4", "Publié."), db)
            with self.assertRaisesRegex(ValueError, "déjà publiée est immuable"):
                compliance_store.save_document(payload("2026.4", "Publié."), db)


if __name__ == "__main__":
    unittest.main()
