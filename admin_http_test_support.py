"""Shared harness for behavioural admin HTTP tests (real Handler, loopback port)."""
from __future__ import annotations

import base64
import http.client
import json
import threading
from http.server import ThreadingHTTPServer

import admin_server


class AdminHttpHarness:
    def __init__(self):
        admin_server.initialize_runtime(background=False)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), admin_server.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def request(self, method, path, body=None, *, cookie="", auth=True, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=10)
        sent = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AdminHttpTest", "Content-Type": "application/json"}
        if auth:
            raw = f"{admin_server.USER}:{admin_server.PASSWORD}".encode()
            sent["Authorization"] = "Basic " + base64.b64encode(raw).decode()
        if cookie:
            sent["Cookie"] = cookie
        sent.update(headers or {})
        payload = json.dumps(body).encode() if body is not None else None
        try:
            connection.request(method, path, body=payload, headers=sent)
            response = connection.getresponse()
            data = response.read()
            try:
                parsed = json.loads(data or b"null")
            except ValueError:
                parsed = None
            return response.status, parsed, response.headers
        finally:
            connection.close()
