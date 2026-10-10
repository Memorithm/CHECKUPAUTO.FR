"""S-10 / S-17 / S-18 behavioural tests against the real admin Handler."""
import base64
import socket
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler
from unittest import mock

import admin_server
from admin_http_test_support import AdminHttpHarness


class AdminServerHardeningTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http = AdminHttpHarness()

    @classmethod
    def tearDownClass(cls):
        cls.http.close()

    def test_non_ascii_basic_credentials_get_401_not_a_crash(self):
        raw = base64.b64encode("adminé:mot-de-passe-é".encode("utf-8")).decode()
        status, _, _ = self.http.request("GET", "/api/admin/auth/2fa/status", auth=False, headers={"Authorization": "Basic " + raw})
        self.assertEqual(status, 401)

    def test_valid_credentials_still_work(self):
        status, _, _ = self.http.request("GET", "/api/admin/auth/2fa/status")
        self.assertEqual(status, 200)

    def test_server_header_does_not_advertise_product_or_python(self):
        _, _, headers = self.http.request("GET", "/api/admin/auth/2fa/status")
        server = headers.get("Server", "")
        self.assertNotIn("CyberCheck", server)
        self.assertNotIn("Python", server)

    def test_stalled_client_is_disconnected(self):
        with mock.patch.object(admin_server.Handler, "timeout", 0.5):
            sock = socket.create_connection(("127.0.0.1", self.http.server.server_address[1]), timeout=5)
            try:
                sock.sendall(b"GET /api/admin/auth/2fa/status HTTP/1.1\r\nHost: x\r\n")
                started = time.monotonic()
                data = sock.recv(1024)
                elapsed = time.monotonic() - started
            finally:
                sock.close()
        self.assertEqual(data, b"")
        self.assertLess(elapsed, 4)


class BoundedServerTest(unittest.TestCase):
    def test_concurrent_handlers_are_capped(self):
        release = threading.Event()
        lock = threading.Lock()
        state = {"active": 0, "peak": 0}

        class Slow(BaseHTTPRequestHandler):
            def do_GET(self):
                with lock:
                    state["active"] += 1
                    state["peak"] = max(state["peak"], state["active"])
                release.wait(5)
                with lock:
                    state["active"] -= 1
                self.send_response(204); self.end_headers()

            def log_message(self, *args):
                pass

        server = admin_server.BoundedThreadingHTTPServer(("127.0.0.1", 0), Slow, max_threads=2)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        clients = []
        try:
            for _ in range(5):
                c = socket.create_connection(server.server_address, timeout=5)
                c.sendall(b"GET / HTTP/1.0\r\n\r\n")
                clients.append(c)
            time.sleep(0.5)
            self.assertEqual(state["peak"], 2)
            release.set()
            for c in clients:
                self.assertIn(b"204", c.recv(64))
        finally:
            release.set()
            for c in clients:
                c.close()
            server.shutdown(); server.server_close()
        self.assertEqual(state["peak"], 2)


if __name__ == "__main__":
    unittest.main()
