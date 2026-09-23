from pathlib import Path
import unittest


class AdminComplianceRegistersUIContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = Path("admin/compliance-registers.html").read_text(encoding="utf-8")
        cls.js = Path("admin/compliance-registers.js").read_text(encoding="utf-8")

    def test_view_exposes_operational_register_sections(self):
        for element_id in (
            "operationsState",
            "operationsActivities",
            "operationsProcessors",
            "operationsBlockers",
            "operationsAttestation",
            "operationsBlockerRows",
            "operationsActivityRows",
            "operationsProcessorRows",
            "operationsRefresh",
        ):
            self.assertIn(f'id="{element_id}"', self.html)
        self.assertIn("Registre des activités de traitement", self.html)
        self.assertIn("Sous-traitants &amp; sous-sous-traitants", self.html)
        self.assertIn('href="/admin/#compliance"', self.html)

    def test_view_uses_authoritative_compliance_snapshot(self):
        self.assertIn("fetch('/api/admin/compliance'", self.js)
        self.assertIn("snapshot?.operations||{}", self.js)
        self.assertIn("operations.processingActivities", self.js)
        self.assertIn("operations.processors", self.js)
        self.assertIn("summary.blockers", self.js)
        self.assertIn("snapshot?.operationalRegisterAttestation||{}", self.js)

    def test_untrusted_register_values_are_rendered_as_text(self):
        self.assertIn("node.textContent=text(value)||'—'", self.js)
        self.assertIn("node.textContent=items.length?items.join(' · '):'—'", self.js)
        self.assertNotIn("innerHTML", self.js)
        self.assertNotIn("insertAdjacentHTML", self.js)
        self.assertNotIn("document.write", self.js)

    def test_page_does_not_embed_secrets_or_inline_script(self):
        self.assertIn('<script src="/admin/compliance-registers.js" defer></script>', self.html)
        self.assertNotIn("<script>", self.html)
        for marker in ("password=", "token=", "secret=", "api_key", "Authorization: Bearer"):
            self.assertNotIn(marker, self.html)
            self.assertNotIn(marker, self.js)


if __name__ == "__main__":
    unittest.main()
