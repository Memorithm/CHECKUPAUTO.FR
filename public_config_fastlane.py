"""CheckupAuto FastLane: anonymous, read-only public configuration microcache.

Fast path ONLY for GET /api/site-config. No HTTP cache, service worker or
session data. Every request stats the config file, so an atomic admin save
changes the cache key immediately. Authentication/cookie-bearing traffic must
continue through the normal security guard and customer server.
"""
from __future__ import annotations

import json
from pathlib import Path
import stat
import threading
import time

import site_config_store

ROUTE = "/api/site-config"
MAX_BYTES = 256 * 1024
_LOCK = threading.RLock()
_ENTRY: tuple[tuple, bytes] | None = None


def eligible(environ: dict) -> bool:
    """Conservative allowlist, never intercept even ambiguous requests."""
    if environ.get("REQUEST_METHOD") != "GET" or environ.get("PATH_INFO") != ROUTE:
        return False
    if environ.get("QUERY_STRING") or environ.get("HTTP_COOKIE") or environ.get("HTTP_AUTHORIZATION"):
        return False
    # Request bodies are never expected on GET, even if maliciously supplied.
    if environ.get("CONTENT_LENGTH") not in (None, "", "0"):
        return False
    if environ.get("HTTP_TRANSFER_ENCODING"):
        return False
    return True


def _source() -> Path:
    runtime = site_config_store.runtime_config_path()
    return runtime if runtime.is_file() else site_config_store.DEFAULT_CONFIG


def _identity(path: Path) -> tuple:
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES or info.st_size == 0:
        raise ValueError("public_config_invalid")
    # Separate cache keys for default->runtime switch, atomic replacement,
    # and same-size edits to the file between requests.
    return (str(path), info.st_dev, info.st_ino, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def response_bytes() -> tuple[bytes, bool]:
    global _ENTRY
    with _LOCK:
        path = _source()
        initial = _identity(path)
        if _ENTRY is not None and _ENTRY[0] == initial:
            return _ENTRY[1], True
        # Existing public endpoint already sends the full public configuration.
        # Cache an immutable serialized snapshot; do not persist a second copy.
        raw = path.read_bytes()
        if len(raw) > MAX_BYTES:
            raise ValueError("public_config_invalid")
        config = json.loads(raw)
        if not isinstance(config, dict):
            raise ValueError("public_config_invalid")
        if _source() != path or _identity(path) != initial:
            raise RuntimeError("public_config_concurrent_update")
        body = json.dumps(config, ensure_ascii=False).encode("utf-8")
        if len(body) > MAX_BYTES:
            raise ValueError("public_config_invalid")
        _ENTRY = (initial, body)
        return body, False


def handle(environ: dict, start_response):
    """Return None to let the existing, guarded application handle traffic."""
    if not eligible(environ):
        return None
    try:
        start = time.perf_counter()
        body, hit = response_bytes()
        duration = max(0.0, (time.perf_counter() - start) * 1000)
        start_response("200 OK", [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-store"),
            ("X-Content-Type-Options", "nosniff"),
            ("Server-Timing", "fastlane;dur=" + format(duration, ".2f")),
            ("X-CheckupAuto-FastLane", "hit" if hit else "miss"),
        ])
        return [body]
    except Exception:
        # No stale-on-error. A bad config must never be cached or leaked.
        # No exception text, paths or request headers leave the process.
        body = b'{"ok":false,"error":"public_config_unavailable"}'
        start_response("503 Service Unavailable", [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-store"),
            ("X-Content-Type-Options", "nosniff"),
        ])
        return [body]
