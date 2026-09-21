import unittest
from unittest.mock import Mock, patch

import mercure_rights


class MercureRightsTest(unittest.TestCase):
    def test_subject_reference_accepts_only_bounded_customer_identifiers(self):
        self.assertEqual(mercure_rights.parse_subject_ref("account:12"), ("account", "12"))
        self.assertEqual(
            mercure_rights.parse_subject_ref("ACCOUNT:Client-12_A"),
            ("account", "Client-12_A"),
        )
        self.assertEqual(mercure_rights.parse_subject_ref("free:client.34"), ("free", "client.34"))
        for value in (
            "",
            "account",
            "account:",
            "account:12/../../admin",
            "account:12?token=x",
            "account:12#fragment",
            "account:client id",
            "account:client:12",
            "other:12",
            "free:" + ("a" * 129),
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                mercure_rights.parse_subject_ref(value)

    @patch.object(mercure_rights.mercure, "_customer_contact")
    @patch.object(mercure_rights.mercure, "_session")
    def test_contact_snapshot_is_bounded_and_explicitly_partial(self, session, contact):
        provider_session = Mock()
        session.return_value = provider_session
        contact.return_value = {
            "email": "client@example.fr",
            "telephone": "+33102030405",
            "provider_secret": "must-not-leak",
        }
        result = mercure_rights.contact_snapshot("account:12")
        session.assert_called_once_with()
        contact.assert_called_once_with(provider_session, "account", "12")
        self.assertEqual(result["provider"], "mercure")
        self.assertEqual(result["subject"], {"clientKind": "account", "clientId": "12"})
        self.assertEqual(result["contact"]["email"], "client@example.fr")
        self.assertEqual(result["contact"]["telephone"], "+33102030405")
        self.assertTrue(result["partial"])
        self.assertTrue(result["coverage"]["contact"])
        self.assertFalse(result["coverage"]["vehicles"])
        self.assertNotIn("must-not-leak", repr(result))
        self.assertNotIn("provider_secret", repr(result))


if __name__ == "__main__":
    unittest.main()
