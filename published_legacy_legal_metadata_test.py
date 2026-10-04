import unittest

import admin_server


class PublishedLegacyLegalMetadataTest(unittest.TestCase):
    def config(self):
        return {"seo":{"canonicalUrl":"https://www.checkupauto.fr","indexingEnabled":False}}

    def base_doc(self):
        return {
            "type":"privacy",
            "title":"Politique de confidentialité",
            "slug":"/confidentialite",
            "body":"Texte juridique hérité. " * 8,
            "version":"legacy-rdv-2026-10-04",
            "publishedAt":"2026-10-04T09:30:31+00:00",
        }

    def test_runtime_published_inherited_document_exposes_version_and_publication_date(self):
        doc=self.base_doc()
        html=admin_server.render_legal_document(doc,self.config()).decode()
        self.assertIn("Version legacy-rdv-2026-10-04 · publiée 2026-10-04T09:30:31+00:00",html)
        self.assertIn("baseline repris du site de réservation actif",html)
        self.assertIn("Continuité documentaire.",html)

    def test_unpublished_fallback_does_not_masquerade_as_runtime_publication(self):
        doc=self.base_doc()
        doc.update({
            "legacyBaseline":True,
            "legacyCapturedAt":"2026-10-04",
            "publishedAt":"",
            "legacySources":["https://rdv.checkupauto.fr/politique_de_confidentialite"],
        })
        html=admin_server.render_legal_document(doc,self.config()).decode()
        self.assertIn("Baseline repris du site de réservation actif · capture 2026-10-04",html)
        self.assertNotIn("Version legacy-rdv-2026-10-04 · publiée",html)

    def test_regular_runtime_document_keeps_standard_version_metadata(self):
        doc=self.base_doc()
        doc["version"]="2026.10.04"
        html=admin_server.render_legal_document(doc,self.config()).decode()
        self.assertIn("Version 2026.10.04 · publiée 2026-10-04T09:30:31+00:00",html)
        self.assertNotIn("Continuité documentaire.",html)


if __name__=="__main__":
    unittest.main()
