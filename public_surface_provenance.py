from __future__ import annotations

import json
from urllib import error, parse, request


MARKER_PATH = "/assets/cybercheck-runtime-marker.bin"
EXPECTED_SCHEMA_VERSION = 1
EXPECTED_SURFACE = "checkupauto-cybercheck"
_MAX_RESPONSE_BYTES = 4096
_TIMEOUT_SECONDS = 5.0
_ALLOWED_CONTENT_TYPES = {"application/json", "text/json", "application/octet-stream"}


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def marker_url(canonical_url: str) -> str:
    parsed = parse.urlsplit(str(canonical_url or "").strip())
    if parsed.scheme != "https" or (parsed.hostname or "").lower() != "www.checkupauto.fr":
        raise ValueError("canonical public URL invalid")
    if parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("canonical public URL invalid")
    return "https://www.checkupauto.fr" + MARKER_PATH


def _opener():
    return request.build_opener(_NoRedirect())


def _result(state: str, *, ok: bool = False) -> dict:
    return {
        "ok": bool(ok),
        "state": str(state),
        "surface": EXPECTED_SURFACE if ok else "",
        "markerPath": MARKER_PATH,
    }


def probe(canonical_url: str, *, opener=None, timeout: float = _TIMEOUT_SECONDS) -> dict:
    try:
        url = marker_url(canonical_url)
    except ValueError:
        return _result("canonical_url_invalid")

    client = opener or _opener()
    req = request.Request(
        url,
        headers={
            "Accept": "application/json, application/octet-stream;q=0.9",
            "User-Agent": "CheckupAuto-Public-Surface-Probe/1",
        },
        method="GET",
    )
    try:
        response = client.open(req, timeout=float(timeout))
        try:
            status = int(getattr(response, "status", response.getcode()))
            if status != 200:
                return _result("unexpected_status")
            content_type = str(response.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
            if content_type not in _ALLOWED_CONTENT_TYPES:
                return _result("invalid_content_type")
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
            if len(raw) > _MAX_RESPONSE_BYTES:
                return _result("response_too_large")
            payload = json.loads(raw.decode("utf-8"))
        finally:
            try:
                response.close()
            except Exception:
                pass
    except error.HTTPError as exc:
        if 300 <= int(exc.code) < 400:
            return _result("redirected")
        if int(exc.code) == 404:
            return _result("marker_not_found")
        return _result("http_error")
    except (error.URLError, TimeoutError, OSError):
        return _result("unavailable")
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        return _result("invalid_marker")

    if not isinstance(payload, dict):
        return _result("invalid_marker")
    if payload.get("schemaVersion") != EXPECTED_SCHEMA_VERSION:
        return _result("invalid_marker")
    if payload.get("surface") != EXPECTED_SURFACE:
        return _result("surface_mismatch")
    if payload.get("purpose") != "public-routing-provenance":
        return _result("invalid_marker")
    return _result("verified", ok=True)
