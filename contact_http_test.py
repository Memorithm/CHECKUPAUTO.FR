import contextlib
import http.client
import importlib
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import urlencode


class ContactHttpTest(unittest.TestCase):
    @contextlib.contextmanager
    def server(self):
        with tempfile.TemporaryDirectory() as private, tempfile.TemporaryDirectory() as data:
            Path(private, "admin-password").write_text("synthetic-test-password\n")
            env = {
                "CYBERCHECK_PRIVATE_DIR": private,
                "CYBERCHECK_DATA_DIR": data,
                "CYBERCHECK_SECURITY_DIR": str(Path(private, "security")),
            }
            with patch.dict(os.environ, env):
                app = importlib.import_module("admin_server")
                with patch.object(app.Handler, "_guard", return_value=True):
                    httpd = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
                    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
                    thread.start()
                    try:
                        yield app, httpd.server_address, Path(data)
                    finally:
                        httpd.shutdown()
                        httpd.server_close()
                        thread.join(timeout=5)

    @staticmethod
    def customer():
        return {
            "accountId": "00000000-0000-4000-8000-000000000001",
            "displayName": "Client Test",
            "email": "client@example.test",
            "phone": "0612345678",
        }

    def test_anonymous_contact_get_and_post_redirect_to_customer_login(self):
        with self.server() as (app, address, data_dir):
            connection = http.client.HTTPConnection(*address, timeout=5)
            try:
                connection.request("GET", "/contact")
                response = connection.getresponse()
                response.read()
            finally:
                connection.close()
            self.assertEqual(response.status, 303)
            self.assertEqual(response.getheader("Location"), "/compte?intent=contact")

            payload = urlencode({
                "category": "general",
                "message": "Ceci est une demande de contact suffisamment longue.",
                "website": "",
                "consent": "yes",
                "csrf": "c" * 64,
            }).encode()
            connection = http.client.HTTPConnection(*address, timeout=5)
            try:
                connection.request(
                    "POST",
                    "/contact",
                    payload,
                    {
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Content-Length": str(len(payload)),
                        "Origin": f"http://{address[0]}:{address[1]}",
                    },
                )
                response = connection.getresponse()
                response.read()
            finally:
                connection.close()
            self.assertEqual(response.status, 303)
            self.assertEqual(response.getheader("Location"), "/compte?intent=contact")
            self.assertFalse((data_dir / "contact-requests.sqlite3").exists())

    def test_authenticated_contact_uses_customer_profile_identity(self):
        with self.server() as (app, address, data_dir):
            customer = self.customer()
            with patch.object(
                app.customer_http, "_account", return_value=("session-token", customer)
            ), patch.object(
                app.customer_http.customer_accounts, "csrf_token", return_value="c" * 64
            ), patch.object(
                app.customer_http.customer_accounts, "verify_csrf", return_value=True
            ):
                connection = http.client.HTTPConnection(*address, timeout=5)
                try:
                    connection.request("GET", "/contact")
                    response = connection.getresponse()
                    body = response.read()
                finally:
                    connection.close()
                self.assertEqual(response.status, 200)
                self.assertIn(b"client@example.test", body)
                self.assertIn("réservé aux clients connectés".encode(), body)
                self.assertNotIn(b'name="email"', body)
                self.assertNotIn(b'name="name"', body)

                payload = urlencode({
                    "category": "refund_request",
                    "message": "Merci de me recontacter au sujet de mon paiement.",
                    "website": "",
                    "consent": "yes",
                    "csrf": "c" * 64,
                }).encode()
                headers = {
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Content-Length": str(len(payload)),
                    "Origin": f"http://{address[0]}:{address[1]}",
                }
                with patch.object(
                    importlib.import_module("payment_payline"),
                    "refund",
                    side_effect=AssertionError("contact must never call Payline refund"),
                ):
                    connection = http.client.HTTPConnection(*address, timeout=5)
                    try:
                        connection.request("POST", "/contact", payload, headers)
                        response = connection.getresponse()
                        confirmation = response.read()
                    finally:
                        connection.close()

            self.assertEqual(response.status, 201)
            self.assertIn("Aucune opération bancaire".encode(), confirmation)
            db_path = data_dir / "contact-requests.sqlite3"
            self.assertTrue(db_path.is_file())
            with sqlite3.connect(db_path) as db:
                row = db.execute(
                    """SELECT customer_account_id,name,email,phone
                       FROM contact_requests"""
                ).fetchone()
            self.assertEqual(
                row,
                (
                    customer["accountId"],
                    customer["displayName"],
                    customer["email"],
                    customer["phone"],
                ),
            )

    def test_authenticated_customer_can_submit_suggestion_intent(self):
        with self.server() as (app, address, data_dir):
            customer=self.customer()
            with patch.object(
                app.customer_http,"_account",return_value=("session-token",customer)
            ), patch.object(
                app.customer_http.customer_accounts,"csrf_token",return_value="c"*64
            ), patch.object(
                app.customer_http.customer_accounts,"verify_csrf",return_value=True
            ):
                connection=http.client.HTTPConnection(*address,timeout=5)
                try:
                    connection.request("GET","/contact?intent=suggestion")
                    response=connection.getresponse()
                    body=response.read()
                finally:
                    connection.close()
                self.assertEqual(response.status,200)
                self.assertIn("Une idée pour nous améliorer".encode(),body)
                self.assertIn(b'name="intent" value="suggestion"',body)

                payload=urlencode({
                    "intent":"suggestion",
                    "category":"general",
                    "message":"Je suggère un rappel plus visible avant la date du contrôle.",
                    "website":"",
                    "consent":"yes",
                    "csrf":"c"*64,
                }).encode()
                headers={
                    "Content-Type":"application/x-www-form-urlencoded",
                    "Content-Length":str(len(payload)),
                    "Origin":f"http://{address[0]}:{address[1]}",
                }
                connection=http.client.HTTPConnection(*address,timeout=5)
                try:
                    connection.request("POST","/contact",payload,headers)
                    response=connection.getresponse()
                    response.read()
                finally:
                    connection.close()
            self.assertEqual(response.status,201)
            with sqlite3.connect(data_dir/"contact-requests.sqlite3") as db:
                row=db.execute(
                    "SELECT customer_account_id,intent,category,message FROM contact_requests"
                ).fetchone()
            self.assertEqual(
                row,
                (
                    customer["accountId"],
                    "suggestion",
                    "general",
                    "Je suggère un rappel plus visible avant la date du contrôle.",
                ),
            )

    def test_authenticated_cross_origin_contact_post_is_rejected(self):
        with self.server() as (app, address, data_dir):
            payload = urlencode({
                "category": "general",
                "message": "Ceci est une demande de contact valide.",
                "website": "",
                "consent": "yes",
                "csrf": "c" * 64,
            }).encode()
            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(payload)),
                "Origin": "https://evil.example",
            }
            with patch.object(
                app.customer_http, "_account", return_value=("session-token", self.customer())
            ), patch.object(
                app.customer_http.customer_accounts, "verify_csrf", return_value=True
            ):
                connection = http.client.HTTPConnection(*address, timeout=5)
                try:
                    connection.request("POST", "/contact", payload, headers)
                    response = connection.getresponse()
                    response.read()
                finally:
                    connection.close()
            self.assertEqual(response.status, 403)
            self.assertFalse((data_dir / "contact-requests.sqlite3").exists())

    def test_authenticated_contact_rejects_free_form_identity_fields(self):
        with self.server() as (app, address, data_dir):
            payload = urlencode({
                "category": "general",
                "email": "outsider@example.test",
                "message": "Tentative de remplacement de l'identité du client.",
                "website": "",
                "consent": "yes",
                "csrf": "c" * 64,
            }).encode()
            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(payload)),
                "Origin": f"http://{address[0]}:{address[1]}",
            }
            with patch.object(
                app.customer_http, "_account", return_value=("session-token", self.customer())
            ), patch.object(
                app.customer_http.customer_accounts, "verify_csrf", return_value=True
            ):
                connection = http.client.HTTPConnection(*address, timeout=5)
                try:
                    connection.request("POST", "/contact", payload, headers)
                    response = connection.getresponse()
                    response.read()
                finally:
                    connection.close()
            self.assertEqual(response.status, 400)
            self.assertFalse((data_dir / "contact-requests.sqlite3").exists())


if __name__ == "__main__":
    unittest.main()
