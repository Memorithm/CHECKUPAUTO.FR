import sqlite3
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import contact_request as contact


class ContactRequestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "contact.sqlite3"

    def payload(self, **overrides):
        data = {
            "category": "refund_request",
            "name": "Client Test",
            "email": "client@example.test",
            "phone": "+33 6 00 00 00 00",
            "message": "Je souhaite être recontacté au sujet de mon paiement.",
            "website": "",
            "consent": "yes",
        }
        data.update(overrides)
        return data

    def test_refund_request_is_contact_only_and_triggers_no_payment_action(self):
        result = contact.submit(self.payload(), path=self.path)
        self.assertRegex(result["requestId"], r"^[0-9a-f]{32}$")
        self.assertEqual(result["category"], "refund_request")
        self.assertFalse(result["paymentActionTriggered"])
        self.assertFalse(result["refundActionTriggered"])
        with sqlite3.connect(self.path) as db:
            row = db.execute(
                "SELECT category,name,email,status FROM contact_requests WHERE request_id=?",
                (result["requestId"],),
            ).fetchone()
        self.assertEqual(row, ("refund_request", "Client Test", "client@example.test", "open"))

    def test_honeypot_and_consent_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "^contact_payload_invalid$"):
            contact.submit(self.payload(website="spam.example"), path=self.path)
        with self.assertRaisesRegex(ValueError, "^contact_consent_required$"):
            contact.submit(self.payload(consent=""), path=self.path)
        self.assertFalse(self.path.exists())

    def test_form_explicitly_states_manual_refund_procedure(self):
        body = contact.render_form()
        self.assertIn(b'action="/contact"', body)
        self.assertIn("ne déclenche aucun remboursement".encode(), body)
        self.assertNotIn(b"/api/admin/payments/refunds", body)
        self.assertNotIn(b"PaylineAPI", body)

    def test_confirmation_never_claims_a_refund(self):
        result = contact.submit(self.payload(category="payment"), path=self.path)
        body = contact.render_confirmation(result)
        self.assertIn("Aucune opération bancaire".encode(), body)
        self.assertIn(result["requestId"].encode(), body)


if __name__ == "__main__":
    unittest.main()
