"""Regression tests: governed admin announcements and the customer marquee."""
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

import customer_announcements as announcements
import customer_http


class CustomerAnnouncementsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = mock.patch.dict(os.environ, {"CYBERCHECK_DATA_DIR": self.temp.name})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_seed_is_visible_once_and_survives_database_reopens(self):
        initial = announcements.list_public()
        self.assertEqual(len(initial), 2)
        self.assertIn("système de fidélité et de parrainage", initial[0]["message"])
        self.assertEqual(initial[1]["message"], announcements.IPHONE_ANNOUNCEMENT)
        self.assertEqual(initial, announcements.list_public())
        self.assertTrue(announcements.data_path().is_file())
        for item in initial:
            announcements.change({"action": "delete", "id": item["id"]})
        self.assertEqual(announcements.list_public(), [])
        self.assertEqual(announcements.list_all(), [])  # No accidental reseeding.

    def test_add_edit_hide_delete_and_reopen(self):
        first = announcements.list_all()[0]
        result = announcements.change({
            "action": "create", "message": "  Horaires   modifiés ", "enabled": False
        })
        self.assertEqual(len(result), 3)
        self.assertEqual(result[-1]["message"], "Horaires modifiés")
        self.assertFalse(result[-1]["enabled"])
        self.assertEqual(len(announcements.list_public()), 2)

        ident = result[-1]["id"]
        announcements.change({
            "action": "update", "id": ident, "message": "Nouveaux horaires",
            "enabled": True
        })
        self.assertEqual([i["id"] for i in announcements.list_public()],
                         [first["id"], result[1]["id"], ident])
        announcements.change({"action": "delete", "id": ident})
        self.assertEqual([i["id"] for i in announcements.list_all()], [first["id"], result[1]["id"]])

    def test_legacy_editorial_db_receives_iphone_campaign_exactly_once(self):
        path = announcements.data_path()
        with sqlite3.connect(path) as db:
            db.execute(
                "CREATE TABLE customer_announcements ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "message TEXT NOT NULL, enabled INTEGER NOT NULL, "
                "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
            db.execute(
                "INSERT INTO customer_announcements "
                "(message,enabled,created_at,updated_at) VALUES (?,1,?,?)",
                (announcements.DEFAULT_ANNOUNCEMENT, "2026-10-01", "2026-10-01")
            )
        first = announcements.list_public()
        self.assertEqual(len(first), 2)
        self.assertEqual(first[-1]["message"], announcements.IPHONE_ANNOUNCEMENT)
        self.assertEqual(first, announcements.list_public())
        # The migration ledger prevents promotional messages being re-seeded
        # after an editorial administrator deliberately deletes them.
        announcements.change({"action": "delete", "id": first[-1]["id"]})
        self.assertEqual(len(announcements.list_public()), 1)
        self.assertEqual(len(announcements.list_all()), 1)

    def test_legacy_disabled_iphone_message_is_not_reenabled(self):
        path = announcements.data_path()
        with sqlite3.connect(path) as db:
            db.execute(
                "CREATE TABLE customer_announcements ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "message TEXT NOT NULL, enabled INTEGER NOT NULL, "
                "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
            for message, enabled in (
                (announcements.DEFAULT_ANNOUNCEMENT, 1),
                (announcements.IPHONE_ANNOUNCEMENT, 0),
            ):
                db.execute(
                    "INSERT INTO customer_announcements "
                    "(message,enabled,created_at,updated_at) VALUES (?,?,?,?)",
                    (message, enabled, "2026-10-01", "2026-10-01")
                )
        self.assertEqual(len(announcements.list_public()), 1)
        self.assertEqual(len(announcements.list_all()), 2)
        self.assertFalse(announcements.list_all()[1]["enabled"])

    def test_invalid_payloads_and_nonexistent_ids_are_rejected(self):
        cases = [
            None,
            {"action": "create", "enabled": True, "message": ""},
            {"action": "create", "enabled": True, "message": "x" * 401},
            {"action": "create", "enabled": 1, "message": "Texte"},
            {"action": "create", "enabled": True, "message": "Texte", "admin": 1},
            {"action": "update", "id": True, "enabled": True, "message": "Texte"},
            {"action": "delete", "id": "1"},
            {"action": "reset"},
        ]
        for case in cases:
            with self.subTest(case=case):
                with self.assertRaises(ValueError):
                    announcements.change(case)
        with self.assertRaises(LookupError):
            announcements.change({"action": "delete", "id": 999999})
        with self.assertRaises(LookupError):
            announcements.change({
                "action": "update", "id": 999999, "message": "x", "enabled": True
            })

    def test_admin_text_is_html_escaped_on_account_page(self):
        item = announcements.list_all()[0]
        announcements.change({
            "action": "update", "id": item["id"], "enabled": True,
            "message": '<img src=x onerror="alert(1)"> & le centre',
        })
        account = {
            "kind": "individual", "displayName": "Client Test",
            "email": "client@example.test", "companyName": "", "siret": "",
            "providers": [], "vehicles": [],
        }
        with mock.patch.object(customer_http.customer_accounts, "csrf_token", return_value="csrf"):
            page = customer_http._dashboard_page("token", account, "nonce-test").decode()
        self.assertIn('id="customerAnnouncements"', page)
        self.assertIn("announcement-track", page)
        self.assertIn("customer-news-progress", page)
        self.assertIn("&lt;img src=x onerror=&quot;alert(1)&quot;&gt;", page)
        self.assertNotIn('<img src=x onerror="alert(1)">', page)
        self.assertIn('nonce="nonce-test"', page)
        self.assertIn("prefers-reduced-motion:reduce", page)

    def test_banner_is_visible_on_login_onboarding_and_dashboard(self):
        account = {
            "kind": "individual", "displayName": "Client Test",
            "email": "client@example.test", "companyName": "", "siret": "",
            "providers": [], "vehicles": [],
        }
        with mock.patch.object(customer_http.customer_accounts, "csrf_token", return_value="csrf"), \
             mock.patch.object(customer_http, "_providers_html", return_value=""):
            pages = {
                "login": customer_http._login_page().decode("utf-8"),
                "onboarding": customer_http._contact_completion_page("token", account).decode("utf-8"),
                "dashboard": customer_http._dashboard_page("token", account, "nonce-test").decode("utf-8"),
            }
        for location, page in pages.items():
            with self.subTest(location=location):
                self.assertEqual(page.count('id="customerAnnouncements"'), 1)
                self.assertIn('class="customer-announcements" aria-label="Informations Checkup Auto">', page)
                self.assertIn("système de fidélité et de parrainage", page)
                self.assertIn("customer-news-progress", page)
                self.assertIn("prefers-reduced-motion:reduce", page)
        self.assertIn("refreshCustomerAnnouncements();", pages["dashboard"])
        self.assertIn("checkupauto:announcements", pages["dashboard"])

    def test_two_editorial_announcements_have_distinct_transition_slides(self):
        from pathlib import Path
        first = announcements.list_all()[0]
        iphone_message = announcements.IPHONE_ANNOUNCEMENT
        with mock.patch.object(customer_http, "_providers_html", return_value=""):
            page = customer_http._login_page().decode("utf-8")
        self.assertEqual(page.count('class="announcement-copy'), 2)
        self.assertEqual(page.count('class="announcement-copy is-active"'), 1)
        self.assertIn(iphone_message, page)
        self.assertIn(first["message"], page)
        self.assertIn('aria-label="Information précédente"', page)
        self.assertIn('aria-label="Information suivante"', page)
        self.assertIn('01 / 02', page)
        self.assertIn('/assets/customer-announcements.js?v=20261016-1', page)
        self.assertIn('customer-news-progress', page)
        self.assertIn('prefers-reduced-motion:reduce', page)
        javascript = (Path(__file__).parent / "assets" / "customer-announcements.js").read_text()
        self.assertIn("checkupauto:announcements", javascript)
        self.assertIn("matchMedia('(prefers-reduced-motion: reduce)')", javascript)
        self.assertIn("slide.textContent = message", javascript)
        self.assertNotIn("innerHTML", javascript)

    def test_banner_is_hidden_when_editor_disables_all_announcements(self):
        for item in announcements.list_all():
            announcements.change({
                "action": "update", "id": item["id"],
                "message": item["message"], "enabled": False,
            })
        with mock.patch.object(customer_http, "_providers_html", return_value=""):
            login = customer_http._login_page().decode("utf-8")
        self.assertIn('aria-label="Informations Checkup Auto" hidden>', login)
        self.assertNotIn(announcements.DEFAULT_ANNOUNCEMENT, login)

    def test_customer_announcement_endpoint_rejects_anonymous_and_non_get(self):
        from customer_http_test import Handler
        anon = Handler(customer_http.ANNOUNCEMENTS_ROUTE)
        with mock.patch.object(customer_http, "_account", return_value=("", None)):
            self.assertTrue(customer_http.handle(anon))
        self.assertEqual(anon.response["status"], 401)
        self.assertNotIn("items", anon.response["json"])

        wrong_method = Handler(customer_http.ANNOUNCEMENTS_ROUTE, command="POST")
        self.assertTrue(customer_http.handle(wrong_method))
        self.assertEqual(wrong_method.response["status"], 405)

        authenticated = Handler(customer_http.ANNOUNCEMENTS_ROUTE)
        with mock.patch.object(customer_http, "_account", return_value=("session", {"accountId": "id"})):
            self.assertTrue(customer_http.handle(authenticated))
        self.assertEqual(authenticated.response["status"], 200)
        self.assertEqual(len(authenticated.response["json"]["items"]), 2)
        self.assertEqual(authenticated.response["headers"]["Cache-Control"], "no-store")


if __name__ == "__main__":
    unittest.main()
