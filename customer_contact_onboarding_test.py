"""Mandatory contact onboarding and contact-page regression tests."""
import unittest
from unittest import mock

import customer_http
from customer_http_test import Handler


class ContactOnboardingTest(unittest.TestCase):
    def incomplete_account(self):
        return {
            "ok": True,
            "accountId": "00000000-0000-4000-8000-000000000001",
            "kind": "individual",
            "displayName": "Client Test",
            "email": "client@example.test",
            "companyName": "",
            "siret": "",
            "surname": "",
            "givenName": "",
            "phone": "",
            "addressLine1": "",
            "addressLine2": "",
            "postalCode": "",
            "city": "",
            "providers": ["google"],
            "contactDetailsComplete": False,
        }

    def test_incomplete_account_redirects_to_mandatory_details(self):
        h = Handler("/compte")
        with mock.patch.object(customer_http, "_account", return_value=("session", self.incomplete_account())):
            self.assertTrue(customer_http.handle(h))
        self.assertEqual(h.response["status"], 303)
        self.assertEqual(h.response["location"], "/compte/completer-coordonnees")

    def test_incomplete_form_is_visible_and_accessible(self):
        h = Handler("/compte/completer-coordonnees")
        with mock.patch.object(customer_http, "_account", return_value=("session", self.incomplete_account())), \
             mock.patch.object(customer_http.customer_accounts, "csrf_token", return_value="x" * 64):
            self.assertTrue(customer_http.handle(h))
        self.assertEqual(h.response["status"], 200)
        body = h.response["data"].decode()
        self.assertIn('name="phone"', body)
        self.assertIn('name="addressLine1"', body)
        self.assertIn('name="postalCode"', body)
        self.assertIn('name="surname"', body)
        self.assertIn('name="givenName"', body)
        self.assertIn('type="submit"', body)
        self.assertIn("required", body)
        self.assertIn("client@example.test", body)

    def test_completed_profile_redirects_to_dashboard(self):
        completed = {**self.incomplete_account(), "contactDetailsComplete": True}
        h = Handler("/compte/completer-coordonnees")
        with mock.patch.object(customer_http, "_account", return_value=("session", completed)):
            self.assertTrue(customer_http.handle(h))
        self.assertEqual(h.response["status"], 303)
        self.assertEqual(h.response["location"], "/compte")

    def test_post_missing_fields_is_rejected_without_update(self):
        h = Handler("/compte/completer-coordonnees", command="POST")
        with mock.patch.object(customer_http, "_account", return_value=("session", self.incomplete_account())), \
             mock.patch.object(customer_http.customer_accounts, "csrf_token", return_value="x" * 64), \
             mock.patch.object(customer_http.customer_accounts, "update_profile") as update, \
             mock.patch.object(customer_http, "_same_origin", return_value=True):
            self.assertTrue(customer_http.handle(h))
        self.assertEqual(h.response["status"], 422)
        self.assertIn("Vérifiez chaque champ obligatoire", h.response["data"].decode())
        update.assert_not_called()

    def test_successful_onboarding_requires_verified_complete_profile(self):
        payload = {
            "csrf": "x" * 64,
            "kind": "individual",
            "displayName": "Client Test",
            "surname": "Test",
            "givenName": "Client",
            "companyName": "",
            "siret": "",
            "phone": "0612345678",
            "addressLine1": "1 rue Niépce",
            "addressLine2": "",
            "postalCode": "78130",
            "city": "Les Mureaux",
        }
        h = Handler("/compte/completer-coordonnees", command="POST")
        with mock.patch.object(customer_http, "_account", return_value=("session", self.incomplete_account())), \
             mock.patch.object(customer_http, "_customer_form", return_value=payload), \
             mock.patch.object(customer_http, "_same_origin", return_value=True), \
             mock.patch.object(customer_http.customer_accounts, "verify_csrf", return_value=True), \
             mock.patch.object(customer_http.customer_accounts, "update_profile",
                               return_value={"contactDetailsComplete": True}) as update:
            self.assertTrue(customer_http.handle(h))
        self.assertEqual(h.response["status"], 303)
        self.assertEqual(h.response["location"], "/compte")
        update.assert_called_once()

    def test_onboarding_rejects_forged_origin_and_csrf(self):
        h = Handler("/compte/completer-coordonnees", command="POST")
        with mock.patch.object(customer_http, "_account", return_value=("session", self.incomplete_account())), \
             mock.patch.object(customer_http.customer_accounts, "csrf_token", return_value="x" * 64), \
             mock.patch.object(customer_http, "_same_origin", return_value=False):
            self.assertTrue(customer_http.handle(h))
        self.assertEqual(h.response["status"], 403)


if __name__ == "__main__":
    unittest.main()
