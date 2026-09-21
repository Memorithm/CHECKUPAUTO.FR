"""Passenger/WSGI entrypoint for CheckupAuto shared-host deployments.

The application itself is still implemented with ``BaseHTTPRequestHandler``.  This
adapter translates one PEP 3333 request into the exact HTTP request consumed by
the existing handler, then translates its response back to WSGI.  Importing this
module does not import ``admin_server`` so build/probe tooling never needs access
to runtime secrets.
"""
from __future__ import annotations

import io
import re
from types import SimpleNamespace
from urllib.parse import quote

MAX_BODY = 131072
_METHOD_RE = re.compile(r"^[A-Z]{1,20}$")
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


class _Capture(io.BytesIO):
    """Bytes buffer which remains readable after a handler closes its stream."""

    def close(self) -> None:  # pragma: no cover - BaseHTTPRequestHandler usually leaves it open
        self.flush()


class _WSGIConnection:
    def __init__(self, request_bytes: bytes):
        self._incoming = io.BytesIO(request_bytes)
        self._outgoing = _Capture()

    def makefile(self, mode: str, buffering: int | None = None):
        del buffering
        if "r" in mode:
            return self._incoming
        if "w" in mode:
            return self._outgoing
        raise ValueError("mode de flux HTTP invalide")

    def settimeout(self, _value) -> None:
        return None

    def sendall(self, data: bytes) -> None:
        self._outgoing.write(data)

    def response_bytes(self) -> bytes:
        return self._outgoing.getvalue()


def _safe_port(value, default: int) -> int:
    try:
        port = int(str(value or default))
    except (TypeError, ValueError):
        return default
    return port if 0 <= port <= 65535 else default


def _request_target(environ: dict) -> str:
    raw = str(environ.get("RAW_URI") or environ.get("REQUEST_URI") or "")
    if raw.startswith("/") and "\r" not in raw and "\n" not in raw:
        return raw

    path = str(environ.get("PATH_INFO") or "/")
    if "\r" in path or "\n" in path:
        raise ValueError("chemin WSGI invalide")
    if not path.startswith("/"):
        path = "/" + path
    target = quote(path, safe="/:@&=+$,;~*'()!-._")
    query = str(environ.get("QUERY_STRING") or "")
    if "\r" in query or "\n" in query:
        raise ValueError("requête WSGI invalide")
    if query:
        target += "?" + query
    return target


def _read_body(environ: dict) -> bytes:
    raw_length = str(environ.get("CONTENT_LENGTH") or "0").strip()
    try:
        length = int(raw_length or "0")
    except ValueError as exc:
        raise ValueError("Content-Length WSGI invalide") from exc
    if length < 0:
        raise ValueError("Content-Length WSGI invalide")
    if length > MAX_BODY:
        raise OverflowError("corps WSGI trop volumineux")
    if not length:
        return b""
    stream = environ.get("wsgi.input")
    if stream is None:
        raise ValueError("flux WSGI absent")
    body = stream.read(length)
    if isinstance(body, str):
        body = body.encode("utf-8")
    if not isinstance(body, (bytes, bytearray)) or len(body) != length:
        raise ValueError("corps WSGI incomplet")
    return bytes(body)


def _request_bytes(environ: dict) -> bytes:
    method = str(environ.get("REQUEST_METHOD") or "GET").upper()
    if not _METHOD_RE.fullmatch(method):
        raise ValueError("méthode WSGI invalide")
    target = _request_target(environ)
    body = _read_body(environ)

    headers: list[tuple[str, str]] = []
    for key, value in environ.items():
        if not key.startswith("HTTP_"):
            continue
        name = key[5:].replace("_", "-")
        if name.lower() in _HOP_BY_HOP or name.lower() == "content-length":
            continue
        text = str(value)
        if "\r" in text or "\n" in text:
            continue
        headers.append((name, text))

    if not any(name.lower() == "host" for name, _ in headers):
        host = str(environ.get("SERVER_NAME") or "localhost")
        port = str(environ.get("SERVER_PORT") or "")
        scheme = str(environ.get("wsgi.url_scheme") or "http").lower()
        default_port = (scheme == "http" and port == "80") or (scheme == "https" and port == "443")
        headers.append(("Host", host if not port or default_port else f"{host}:{port}"))

    content_type = str(environ.get("CONTENT_TYPE") or "")
    if content_type and "\r" not in content_type and "\n" not in content_type:
        headers.append(("Content-Type", content_type))
    headers.append(("Content-Length", str(len(body))))
    headers.append(("Connection", "close"))

    request_line = f"{method} {target} HTTP/1.1\r\n".encode("ascii")
    header_block = "".join(f"{name}: {value}\r\n" for name, value in headers).encode("iso-8859-1")
    return request_line + header_block + b"\r\n" + body


def _plain_error(start_response, status: str, body: bytes):
    start_response(status, [
        ("Content-Type", "text/plain; charset=utf-8"),
        ("Content-Length", str(len(body))),
        ("Cache-Control", "no-store"),
        ("X-Content-Type-Options", "nosniff"),
    ])
    return [body]


def _serve(handler_class, environ: dict, start_response):
    try:
        request_bytes = _request_bytes(environ)
    except OverflowError:
        return _plain_error(start_response, "413 Payload Too Large", b"Request entity too large")
    except (TypeError, ValueError, UnicodeError):
        return _plain_error(start_response, "400 Bad Request", b"Bad request")

    connection = _WSGIConnection(request_bytes)
    client = (
        str(environ.get("REMOTE_ADDR") or "127.0.0.1"),
        _safe_port(environ.get("REMOTE_PORT"), 0),
    )
    server = SimpleNamespace(
        server_name=str(environ.get("SERVER_NAME") or "localhost"),
        server_port=_safe_port(environ.get("SERVER_PORT"), 80),
    )
    handler_class(connection, client, server)

    raw = connection.response_bytes()
    head, separator, body = raw.partition(b"\r\n\r\n")
    if not separator:
        raise RuntimeError("réponse HTTP CheckupAuto invalide")
    lines = head.decode("iso-8859-1").split("\r\n")
    status_parts = lines[0].split(" ", 2)
    if len(status_parts) < 2 or not status_parts[1].isdigit():
        raise RuntimeError("statut HTTP CheckupAuto invalide")
    code = int(status_parts[1])
    reason = status_parts[2] if len(status_parts) > 2 else ""
    status = f"{code} {reason}".strip()

    response_headers: list[tuple[str, str]] = []
    for line in lines[1:]:
        if not line or ":" not in line:
            continue
        name, value = line.split(":", 1)
        if name.strip().lower() in _HOP_BY_HOP:
            continue
        response_headers.append((name.strip(), value.strip()))
    start_response(status, response_headers)
    return [body]


def application(environ, start_response):
    """PEP 3333 callable discovered by Passenger."""
    from admin_server import Handler  # Lazy: runtime secrets are only required when serving.

    return _serve(Handler, environ, start_response)
