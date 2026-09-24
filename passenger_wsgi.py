from __future__ import annotations

from http.server import ThreadingHTTPServer
from pathlib import Path
import http.client
import ipaddress
import json
import os
import secrets
import subprocess
import threading
import time
from urllib.parse import quote

import public_surface_provenance

_BACKEND_LOCK = threading.RLock()
_BACKEND_SERVER = None
_BACKEND_THREAD = None
_PROXY_TOKEN = secrets.token_urlsafe(32)
_PROVENANCE_LOCK = threading.RLock()
_PROVENANCE_CACHE = (0.0, b"")
_PROVENANCE_CACHE_SECONDS = 5.0
_ROOT = Path(__file__).resolve().parent
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


def _git_output(*args: str) -> str:
    return subprocess.run(
        ["git", "-c", f"safe.directory={_ROOT}", "-C", str(_ROOT), *args],
        capture_output=True,
        text=True,
        timeout=4,
        check=True,
    ).stdout.strip()


def _runtime_git_state() -> dict:
    try:
        head = _git_output("rev-parse", "HEAD")
        branch = _git_output("rev-parse", "--abbrev-ref", "HEAD")
        status = _git_output("status", "--porcelain=v1")
        return {"available": True, "head": head, "branch": branch, "dirty": bool(status)}
    except Exception:
        return {"available": False, "head": "", "branch": "", "dirty": None}


def _public_provenance_body() -> bytes:
    global _PROVENANCE_CACHE
    now = time.monotonic()
    with _PROVENANCE_LOCK:
        cached_at, cached = _PROVENANCE_CACHE
        if cached and now - cached_at < _PROVENANCE_CACHE_SECONDS:
            return cached
        payload = public_surface_provenance.runtime_evidence(_runtime_git_state())
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        _PROVENANCE_CACHE = (now, raw)
        return raw


def _public_provenance_response(environ: dict, start_response):
    method = str(environ.get("REQUEST_METHOD") or "GET").upper()
    path = str(environ.get("PATH_INFO") or "/")
    if path != public_surface_provenance.DEPLOYMENT_PROVENANCE_PATH or method not in {"GET", "HEAD"}:
        return None
    payload = _public_provenance_body()
    start_response(
        "200 OK",
        [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(payload))),
            ("Cache-Control", "no-store"),
            ("X-Content-Type-Options", "nosniff"),
        ],
    )
    return [b"" if method == "HEAD" else payload]


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
        direct = _public_provenance_response(environ, start_response)
        if direct is not None:
            return direct

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
