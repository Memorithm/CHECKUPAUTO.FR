import io
import unittest
from http.server import BaseHTTPRequestHandler

import passenger_wsgi as adapter


class ProbeHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    calls = 0

    def log_message(self, _format, *args):
        return

    def do_GET(self):
        type(self).calls += 1
        body = "|".join([
            self.path,
            self.headers.get("Host", ""),
            self.headers.get("X-Checkup-Test", ""),
            self.client_address[0],
        ]).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        type(self).calls += 1
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        self.send_response(201)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class ForbiddenRead:
    def read(self, _size=-1):
        raise AssertionError("oversized request body must not be read")


class PassengerWSGITest(unittest.TestCase):
    def setUp(self):
        ProbeHandler.calls = 0

    def invoke(self, **changes):
        environ = {
            "REQUEST_METHOD": "GET",
            "PATH_INFO": "/health",
            "QUERY_STRING": "",
            "SERVER_NAME": "www.checkupauto.fr",
            "SERVER_PORT": "443",
            "wsgi.url_scheme": "https",
            "REMOTE_ADDR": "203.0.113.10",
            "REMOTE_PORT": "43120",
            "wsgi.input": io.BytesIO(),
            "CONTENT_LENGTH": "0",
        }
        environ.update(changes)
        captured = {}

        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = headers

        body = b"".join(adapter._serve(ProbeHandler, environ, start_response))
        captured["body"] = body
        return captured

    def test_forwards_path_query_host_headers_and_remote_address(self):
        response = self.invoke(
            PATH_INFO="/échéances",
            QUERY_STRING="vehicle=42",
            HTTP_HOST="checkupauto.fr",
            HTTP_X_CHECKUP_TEST="bridge-ok",
        )
        self.assertEqual(response["status"], "200 OK")
        self.assertEqual(
            response["body"].decode(),
            "/%C3%A9ch%C3%A9ances?vehicle=42|checkupauto.fr|bridge-ok|203.0.113.10",
        )
        names = {name.lower() for name, _ in response["headers"]}
        self.assertNotIn("connection", names)

    def test_forwards_request_body_exactly(self):
        payload = b'{"ok":true}'
        response = self.invoke(
            REQUEST_METHOD="POST",
            PATH_INFO="/api/test",
            CONTENT_TYPE="application/json",
            CONTENT_LENGTH=str(len(payload)),
            **{"wsgi.input": io.BytesIO(payload)},
        )
        self.assertEqual(response["status"], "201 Created")
        self.assertEqual(response["body"], payload)

    def test_oversized_body_is_rejected_before_handler_or_stream_read(self):
        response = self.invoke(
            REQUEST_METHOD="POST",
            CONTENT_LENGTH=str(adapter.MAX_BODY + 1),
            **{"wsgi.input": ForbiddenRead()},
        )
        self.assertEqual(response["status"], "413 Payload Too Large")
        self.assertEqual(ProbeHandler.calls, 0)
        self.assertIn(("Cache-Control", "no-store"), response["headers"])

    def test_invalid_content_length_is_fail_closed(self):
        response = self.invoke(CONTENT_LENGTH="not-a-number")
        self.assertEqual(response["status"], "400 Bad Request")
        self.assertEqual(ProbeHandler.calls, 0)

    def test_raw_uri_with_crlf_is_not_trusted(self):
        response = self.invoke(
            RAW_URI="/safe\r\nX-Injected: yes",
            PATH_INFO="/safe",
        )
        self.assertEqual(response["status"], "200 OK")
        self.assertTrue(response["body"].startswith(b"/safe|"))


if __name__ == "__main__":
    unittest.main()
