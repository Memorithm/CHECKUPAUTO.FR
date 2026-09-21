import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class PublicComplianceContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = (ROOT / "admin_server.py").read_text(encoding="utf-8")
        cls.index = (ROOT / "index.html").read_text(encoding="utf-8")
        cls.withdrawal = (ROOT / "withdrawal_service.py").read_text(encoding="utf-8")

    def test_public_legal_documents_are_served_from_published_store(self):
        self.assertIn("if path in compliance.SLUG_TO_DOCUMENT:", self.server)
        self.assertIn("compliance.public_document_for_path(path)", self.server)
        self.assertIn("render_legal_document(doc,load_config())", self.server)

    def test_withdrawal_has_public_get_and_post_routes(self):
        self.assertIn("if path=='/retractation':", self.server)
        self.assertIn("withdrawals.render_page(", self.server)
        self.assertIn("withdrawals.submit(payload)", self.server)
        self.assertIn("if path=='/api/compliance/withdrawal':", self.server)

    def test_footer_exposes_unambiguous_withdrawal_action(self):
        self.assertIn(
            '<a href="/retractation">Renoncer au contrat ici</a>',
            self.index,
        )

    def test_receipt_retry_is_privacy_bounded(self):
        self.assertIn("receipt_email=CASE WHEN ?='sent' THEN '' ELSE receipt_email END", self.withdrawal)
        self.assertIn("receipt_email_hash", self.withdrawal)
        self.assertIn("declaration_hash", self.withdrawal)


if __name__ == "__main__":
    unittest.main()
