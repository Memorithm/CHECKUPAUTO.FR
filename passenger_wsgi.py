from __future__ import annotations

from http.server import ThreadingHTTPServer
from contextlib import contextmanager
import errno
import fcntl
import stat
from pathlib import Path
import http.client
import ipaddress
import json
import os
import secrets
import sys
import subprocess
import threading
import time
from urllib.parse import quote

import public_surface_provenance
import migration_write_freeze

_BACKEND_LOCK = threading.RLock()
_BACKEND_SERVER = None
_BACKEND_THREAD = None
_BACKEND_PID = None
_PROXY_TOKEN = secrets.token_urlsafe(32)
_PROVENANCE_LOCK = threading.RLock()
_PROVENANCE_CACHE = (0.0, b"")
_PROVENANCE_CACHE_SECONDS = 5.0
_ROOT = Path(__file__).resolve().parent
_RELEASE_MARKER_NAME = ".checkupauto-release.json"
_RELEASE_MARKER_MAX_BYTES = 2048
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
DEFAULT_BODY_LIMIT = 131072
# Routes accepting file uploads keep the backend's own limit (customer_ct_reports.MAX_UPLOAD_BYTES).
UPLOAD_BODY_LIMITS = {
    ("POST", "/api/customer/reports"): 12 * 1024 * 1024,
}
_INTERNAL_HEADERS = {
    "x-checkupauto-proxy-token",
    "x-checkupauto-client-ip",
}


@contextmanager
def _runtime_initialization_lock(data_dir):
    """Serialize schema/seed writes across Passenger worker processes.

    All cold workers previously ran the same SQLite CREATE/seed sequence at
    once, producing SQLITE_BUSY and downstream 503 responses. The lock lives
    beside the runtime database, never in the immutable release directory.
    """
    directory = Path(data_dir)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / ".passenger-runtime-init.lock"
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
            raise PermissionError("runtime initialization lock invalid")
        deadline = time.monotonic() + 12.0
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in (errno.EAGAIN, errno.EACCES):
                    raise
                if time.monotonic() >= deadline:
                    raise TimeoutError("runtime initialization lock timeout") from None
                time.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _ensure_backend() -> tuple[str, int]:
    global _BACKEND_SERVER, _BACKEND_THREAD, _BACKEND_PID
    with _BACKEND_LOCK:
        pid = os.getpid()
        if _BACKEND_SERVER is not None:
            if (_BACKEND_PID == pid and _BACKEND_THREAD is not None
                    and _BACKEND_THREAD.is_alive()):
                host, port = _BACKEND_SERVER.server_address[:2]
                return str(host), int(port)
            # Passenger may fork/recycle a worker after module import, or the
            # loopback serving thread may have exited. Never reuse a stale port.
            try:
                _BACKEND_SERVER.server_close()
            except OSError:
                pass
            _BACKEND_SERVER = None
            _BACKEND_THREAD = None
            _BACKEND_PID = None

        import admin_server

        os.chdir(admin_server.ROOT)
        admin_server.configure_internal_proxy(_PROXY_TOKEN)
        with _runtime_initialization_lock(admin_server.analytics.DB.parent):
            admin_server.initialize_runtime(background=False)
        server = ThreadingHTTPServer(("127.0.0.1", 0), admin_server.Handler)
        thread = threading.Thread(
            target=server.serve_forever,
            daemon=True,
            name="CheckupAutoPassengerBridge",
        )
        try:
            thread.start()
        except Exception:
            server.server_close()
            raise
        _BACKEND_SERVER = server
        _BACKEND_THREAD = thread
        _BACKEND_PID = pid
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


def _body_limit(environ: dict) -> int:
    method = str(environ.get("REQUEST_METHOD") or "GET").upper()
    path = str(environ.get("PATH_INFO") or "/")
    return UPLOAD_BODY_LIMITS.get((method, path), DEFAULT_BODY_LIMIT)


def _request_body(environ: dict) -> bytes:
    raw = str(environ.get("CONTENT_LENGTH") or "").strip()
    if not raw:
        return b""
    try:
        length = int(raw)
    except ValueError as exc:
        raise ValueError("CONTENT_LENGTH invalide") from exc
    if length < 0 or length > _body_limit(environ):
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


def _runtime_release_marker_sha() -> str:
    """Read only the immutable archive revision marker created by deployment_release."""
    marker = _ROOT / _RELEASE_MARKER_NAME
    try:
        if not marker.is_file() or marker.is_symlink():
            return ""
        raw = marker.read_bytes()
        if not raw or len(raw) > _RELEASE_MARKER_MAX_BYTES:
            return ""
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict) or payload.get("schemaVersion") != 1 or payload.get("verified") is not True:
            return ""
        sha = str(payload.get("sha") or "").strip().lower()
        digest = str(payload.get("archiveSha256") or "").strip().lower()
        hexchars = set("0123456789abcdef")
        if len(sha) != 40 or any(ch not in hexchars for ch in sha):
            return ""
        if len(digest) != 64 or any(ch not in hexchars for ch in digest):
            return ""
        if _ROOT.name != sha:
            return ""
        return sha
    except Exception:
        return ""


def _public_provenance_body() -> bytes:
    global _PROVENANCE_CACHE
    now = time.monotonic()
    with _PROVENANCE_LOCK:
        cached_at, cached = _PROVENANCE_CACHE
        if cached and now - cached_at < _PROVENANCE_CACHE_SECONDS:
            return cached
        git_state = _runtime_git_state()
        if git_state.get("available") is True:
            payload = public_surface_provenance.runtime_evidence(git_state)
        else:
            release_sha = _runtime_release_marker_sha()
            payload = (
                public_surface_provenance.deployment_artifact_evidence(release_sha)
                if release_sha
                else public_surface_provenance.runtime_evidence(git_state)
            )
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


def _mobile_bootstrap_response(environ: dict, start_response):
    """Serve the public, read-only bootstrap without booting the admin backend.

    Passenger may recycle workers between requests. Starting admin_server and
    its background services on a cold GET caused intermittent 8-12s latency
    and blocked the iOS release gate. Keep the payload generated from the
    same validated runtime configuration and mobile_bootstrap.status().
    """
    method = str(environ.get("REQUEST_METHOD") or "GET").upper()
    path = str(environ.get("PATH_INFO") or "/")
    if path != "/api/mobile/bootstrap" or method not in {"GET", "HEAD"}:
        return None
    try:
        import mobile_bootstrap
        import site_config_store

        payload = mobile_bootstrap.status(site_config_store.load())
        body = json.dumps(
            payload, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        status = "200 OK"
    except Exception:
        body = b'{"ok":false,"error":"mobile_bootstrap_unavailable"}'
        status = "503 Service Unavailable"
    start_response(
        status,
        [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-store"),
            ("X-Content-Type-Options", "nosniff"),
        ],
    )
    return [b"" if method == "HEAD" else body]


def _write_freeze_response(environ: dict, start_response):
    method = str(environ.get("REQUEST_METHOD") or "GET").upper()
    path = str(environ.get("PATH_INFO") or "/")
    state = migration_write_freeze.status()
    if not state.get("active"):
        return None
    if migration_write_freeze.request_allowed(method, path):
        return None
    payload = b'{"ok":false,"error":"migration_write_frozen"}'
    start_response(
        "503 Service Unavailable",
        [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(payload))),
            ("Cache-Control", "no-store"),
            ("Retry-After", "120"),
            ("X-CheckupAuto-Migration-Freeze", "active"),
        ],
    )
    return [payload]


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
        frozen = _write_freeze_response(environ, start_response)
        if frozen is not None:
            return frozen
        bootstrap = _mobile_bootstrap_response(environ, start_response)
        if bootstrap is not None:
            return bootstrap

        stage = "backend_start"
        host, port = _ensure_backend()
        stage = "loopback_proxy"
        method = str(environ.get("REQUEST_METHOD") or "GET").upper()
        target = _request_target(environ)
        body = _request_body(environ)
        headers = _request_headers(environ)

        connection = http.client.HTTPConnection(host, port, timeout=20)
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
    except Exception as exc:
        # Diagnostic without request paths, query strings, cookies, credentials
        # or exception messages. OAuth state and PKCE must never enter logs.
        # sqlite_errorname is a finite SQLite constant (e.g. SQLITE_BUSY).
        # Never log sqlite exception messages: they can include file paths.
        raw_code = getattr(exc, "sqlite_errorname", None)
        sqlite_code = (
            raw_code if isinstance(raw_code, str)
            and raw_code.startswith("SQLITE_")
            and raw_code.replace("_", "").isalnum()
            and len(raw_code) <= 48 else "unknown"
        )
        print(
            "CHECKUPAUTO_PASSENGER_BRIDGE_FAILURE"
            f" stage={locals().get('stage', 'preflight')}"
            f" class={type(exc).__name__}"
            f" sqlite={sqlite_code}",
            file=sys.stderr, flush=True,
        )
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
