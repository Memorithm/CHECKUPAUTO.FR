import sqlite3
from pathlib import Path
import tempfile
import unittest

import contact_request as contact


class ContactRequestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "contact.sqlite3"

    def customer(self, **overrides):
        data = {
            "accountId": "00000000-0000-4000-8000-000000000001",
            "displayName": "Client Test",
            "email": "client@example.test",
            "phone": "+33 6 00 00 00 00",
        }
        data.update(overrides)
        return data

    def payload(self, **overrides):
        data = {
            "category": "refund_request",
            "message": "Je souhaite être recontacté au sujet de mon paiement.",
            "website": "",
            "consent": "yes",
        }
        data.update(overrides)
        return data

    def test_refund_request_is_customer_bound_and_triggers_no_payment_action(self):
        customer = self.customer()
        result = contact.submit(self.payload(), customer=customer, path=self.path)
        self.assertRegex(result["requestId"], r"^[0-9a-f]{32}$")
        self.assertEqual(result["customerAccountId"], customer["accountId"])
        self.assertEqual(result["category"], "refund_request")
        self.assertFalse(result["paymentActionTriggered"])
        self.assertFalse(result["refundActionTriggered"])
        with sqlite3.connect(self.path) as db:
            row = db.execute(
                """SELECT customer_account_id,category,name,email,phone,status
                   FROM contact_requests WHERE request_id=?""",
                (result["requestId"],),
            ).fetchone()
        self.assertEqual(
            row,
            (
                customer["accountId"],
                "refund_request",
                "Client Test",
                "client@example.test",
                "+33 6 00 00 00 00",
                "open",
            ),
        )

    def test_free_form_identity_and_missing_customer_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "^contact_customer_required$"):
            contact.submit(self.payload(), customer={}, path=self.path)
        with self.assertRaisesRegex(ValueError, "^contact_payload_invalid$"):
            contact.submit(
                self.payload(email="outsider@example.test"),
                customer=self.customer(),
                path=self.path,
            )
        self.assertFalse(self.path.exists())

    def test_honeypot_and_consent_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "^contact_payload_invalid$"):
            contact.submit(
                self.payload(website="spam.example"),
                customer=self.customer(),
                path=self.path,
            )
        with self.assertRaisesRegex(ValueError, "^contact_consent_required$"):
            contact.submit(
                self.payload(consent=""),
                customer=self.customer(),
                path=self.path,
            )
        self.assertFalse(self.path.exists())

    def test_form_is_customer_only_and_uses_profile_identity(self):
        body = contact.render_form(self.customer(), "c" * 64)
        self.assertIn(b'action="/contact"', body)
        self.assertIn(b'name="csrf"', body)
        self.assertIn(b"client@example.test", body)
        self.assertIn("Ce formulaire est réservé aux clients connectés".encode(), body)
        self.assertNotIn(b'name="name"', body)
        self.assertNotIn(b'name="email"', body)
        self.assertNotIn(b'name="phone"', body)
        self.assertIn(b'href="/compte"', body)
        self.assertIn("ne déclenche aucun remboursement".encode(), body)
        self.assertNotIn(b"/api/admin/payments/refunds", body)
        self.assertNotIn(b"PaylineAPI", body)

    def test_confirmation_never_claims_a_refund(self):
        result = contact.submit(
            self.payload(category="payment"),
            customer=self.customer(),
            path=self.path,
        )
        body = contact.render_confirmation(result)
        self.assertIn("Aucune opération bancaire".encode(), body)
        self.assertIn(result["requestId"].encode(), body)
        self.assertIn(b'href="/compte"', body)


if __name__ == "__main__":
    unittest.main()
