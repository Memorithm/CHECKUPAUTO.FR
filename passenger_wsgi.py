from __future__ import annotations

from http.server import ThreadingHTTPServer
import http.client
import ipaddress
import os
import secrets
import threading
from urllib.parse import quote

_BACKEND_LOCK = threading.RLock()
_BACKEND_SERVER = None
_BACKEND_THREAD = None
_PROXY_TOKEN = secrets.token_urlsafe(32)
_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}
_INTERNAL_HEADERS = {
    "x-checkupauto-proxy-token",
    "x-checkupauto-client-ip",
}


def _ensure_backend() -> tuple[str, int]:
    global _BACKEND_SERVER, _BACKEND_THREAD
    with _BACKEND_LOCK:
        if _BACKEND_SERVER is not None:
            host, port = _BACKEND_SERVER.server_address[:2]
            return str(host), int(port)

        import admin_server

        os.chdir(admin_server.ROOT)
        admin_server.configure_internal_proxy(_PROXY_TOKEN)
        admin_server.initialize_runtime(background=False)
        server = ThreadingHTTPServer(("127.0.0.1", 0), admin_server.Handler)
        thread = threading.Thread(
            target=server.serve_forever,
            daemon=True,
            name="CheckupAutoPassengerBridge",
        )
        thread.start()
        _BACKEND_SERVER = server
        _BACKEND_THREAD = thread
        host, port = server.server_address[:2]
        return str(host), int(port)


def _client_ip(environ: dict) -> str:
    raw = str(environ.get("REMOTE_ADDR") or "").strip()
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError:
        return "127.0.0.1"


def _request_target(environ: dict) -> str:
    raw_path = str(environ.get("PATH_INFO") or "/")
    if not raw_path.startswith("/"):
        raw_path = "/" + raw_path
    path = quote(raw_path, safe="/%:@+~!$&'()*;,=-._")
    query = str(environ.get("QUERY_STRING") or "")
    return path + (("?" + query) if query else "")


def _request_headers(environ: dict) -> dict[str, str]:
    headers: dict[str, str] = {}
    for key, value in environ.items():
        if not key.startswith("HTTP_"):
            continue
        name = key[5:].replace("_", "-").lower()
        if name in _HOP_BY_HOP or name in _INTERNAL_HEADERS or name == "content-length":
            continue
        headers["-".join(part.capitalize() for part in name.split("-"))] = str(value)

    content_type = str(environ.get("CONTENT_TYPE") or "")
    if content_type:
        headers["Content-Type"] = content_type

    headers["X-CheckupAuto-Proxy-Token"] = _PROXY_TOKEN
    headers["X-CheckupAuto-Client-IP"] = _client_ip(environ)
    return headers


def _request_body(environ: dict) -> bytes:
    raw = str(environ.get("CONTENT_LENGTH") or "").strip()
    if not raw:
        return b""
    try:
        length = int(raw)
    except ValueError as exc:
        raise ValueError("CONTENT_LENGTH invalide") from exc
    if length < 0 or length > 131072:
        raise ValueError("corps WSGI trop volumineux")
    if length == 0:
        return b""
    stream = environ.get("wsgi.input")
    if stream is None:
        raise ValueError("flux WSGI absent")
    body = stream.read(length)
    if not isinstance(body, (bytes, bytearray)):
        raise ValueError("flux WSGI invalide")
    if len(body) != length:
        raise ValueError("corps WSGI incomplet")
    return bytes(body)


class _ResponseIterable:
    def __init__(self, response, connection):
        self.response = response
        self.connection = connection

    def __iter__(self):
        try:
            while True:
                chunk = self.response.read(64 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            self.connection.close()

    def close(self):
        self.connection.close()


def application(environ, start_response):
    try:
        host, port = _ensure_backend()
        method = str(environ.get("REQUEST_METHOD") or "GET").upper()
        target = _request_target(environ)
        body = _request_body(environ)
        headers = _request_headers(environ)

        connection = http.client.HTTPConnection(host, port, timeout=60)
        connection.request(method, target, body=body, headers=headers)
        response = connection.getresponse()

        outgoing = []
        for name, value in response.getheaders():
            if name.lower() in _HOP_BY_HOP:
                continue
            outgoing.append((name, value))
        reason = response.reason or "Unknown"
        start_response(f"{response.status} {reason}", outgoing)
        return _ResponseIterable(response, connection)
    except ValueError:
        payload = b'{"ok":false,"error":"invalid_wsgi_request"}'
        start_response(
            "400 Bad Request",
            [
                ("Content-Type", "application/json; charset=utf-8"),
                ("Content-Length", str(len(payload))),
                ("Cache-Control", "no-store"),
            ],
        )
        return [payload]
    except Exception:
        payload = b'{"ok":false,"error":"passenger_bridge_failed"}'
        start_response(
            "503 Service Unavailable",
            [
                ("Content-Type", "application/json; charset=utf-8"),
                ("Content-Length", str(len(payload))),
                ("Cache-Control", "no-store"),
            ],
        )
        return [payload]
