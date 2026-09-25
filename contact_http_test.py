import contextlib
import http.client
import importlib
import os
from pathlib import Path
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

    def test_contact_page_and_refund_request_are_manual_only(self):
        with self.server() as (app, address, data_dir):
            connection = http.client.HTTPConnection(*address, timeout=5)
            try:
                connection.request("GET", "/contact")
                response = connection.getresponse()
                body = response.read()
            finally:
                connection.close()
            self.assertEqual(response.status, 200)
            self.assertIn("ne déclenche aucun remboursement".encode(), body)

            payload = urlencode({
                "category": "refund_request",
                "name": "Client Test",
                "email": "client@example.test",
                "phone": "",
                "message": "Merci de me recontacter au sujet de mon paiement.",
                "website": "",
                "consent": "yes",
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
            self.assertTrue((data_dir / "contact-requests.sqlite3").is_file())

    def test_cross_origin_contact_post_is_rejected(self):
        with self.server() as (app, address, data_dir):
            payload = urlencode({
                "category": "general",
                "name": "Client Test",
                "email": "client@example.test",
                "message": "Ceci est une demande de contact valide.",
                "website": "",
                "consent": "yes",
            }).encode()
            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(payload)),
                "Origin": "https://evil.example",
            }
            connection = http.client.HTTPConnection(*address, timeout=5)
            try:
                connection.request("POST", "/contact", payload, headers)
                response = connection.getresponse()
                response.read()
            finally:
                connection.close()
            self.assertEqual(response.status, 403)
            self.assertFalse((data_dir / "contact-requests.sqlite3").exists())


if __name__ == "__main__":
    unittest.main()
