from __future__ import annotations

import json
import re
from urllib import error, parse, request


MARKER_PATH = "/assets/cybercheck-runtime-marker.bin"
DEPLOYMENT_PROVENANCE_PATH = "/api/public/deployment-provenance"
DEPLOYMENT_ARTIFACT_PATH = "/assets/cybercheck-deployment-provenance.bin"
EXPECTED_SCHEMA_VERSION = 1
EXPECTED_SURFACE = "checkupauto-cybercheck"
_MAX_RESPONSE_BYTES = 4096
_TIMEOUT_SECONDS = 5.0
_ALLOWED_CONTENT_TYPES = {"application/json", "text/json", "application/octet-stream"}
_JSON_CONTENT_TYPES = {"application/json", "text/json"}
_SHA_RE = re.compile(r"[0-9a-f]{40}")


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _canonical_public_url(canonical_url: str, path: str) -> str:
    parsed = parse.urlsplit(str(canonical_url or "").strip())
    if parsed.scheme != "https" or (parsed.hostname or "").lower() != "www.checkupauto.fr":
        raise ValueError("canonical public URL invalid")
    if parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("canonical public URL invalid")
    return "https://www.checkupauto.fr" + path


def marker_url(canonical_url: str) -> str:
    return _canonical_public_url(canonical_url, MARKER_PATH)


def deployment_provenance_url(canonical_url: str) -> str:
    return _canonical_public_url(canonical_url, DEPLOYMENT_PROVENANCE_PATH)


def _opener():
    return request.build_opener(_NoRedirect())


def _result(state: str, *, ok: bool = False) -> dict:
    return {
        "ok": bool(ok),
        "state": str(state),
        "surface": EXPECTED_SURFACE if ok else "",
        "markerPath": MARKER_PATH,
    }


def _deployment_result(state: str, *, ok: bool = False, sha: str = "") -> dict:
    return {
        "ok": bool(ok),
        "state": str(state),
        "surface": EXPECTED_SURFACE if ok else "",
        "provenancePath": DEPLOYMENT_PROVENANCE_PATH,
        "gitSha": sha if ok else "",
        "branch": "main" if ok else "",
        "clean": True if ok else None,
    }


def runtime_evidence(git_state: dict) -> dict:
    """Return the minimal non-secret public proof for the running checkout."""
    state = git_state if isinstance(git_state, dict) else {}
    available = state.get("available") is True
    head = str(state.get("head") or "")
    branch = str(state.get("branch") or "")
    dirty = state.get("dirty")

    reason = "verified"
    if not available:
        reason = "git_unavailable"
    elif not _SHA_RE.fullmatch(head):
        reason = "invalid_git_sha"
    elif branch != "main":
        reason = "wrong_branch"
    elif dirty is not False:
        reason = "dirty_worktree"

    verified = reason == "verified"
    return {
        "schemaVersion": EXPECTED_SCHEMA_VERSION,
        "surface": EXPECTED_SURFACE,
        "purpose": "public-deployment-provenance",
        "verified": verified,
        "state": reason,
        "gitSha": head if _SHA_RE.fullmatch(head) else "",
        "branch": "main" if branch == "main" else "",
        "clean": dirty is False if isinstance(dirty, bool) else None,
    }


def deployment_artifact_evidence(approved_sha: str) -> dict:
    """Return minimal provenance for an immutable RemoteOps-approved git archive.

    Hostinger releases are created from ``git archive <approved SHA>`` rather
    than a live checkout, so there is intentionally no ``.git`` directory in
    the deployed image.  The release directory name is therefore the trusted
    immutable revision input.  Invalid revisions fail closed and never claim
    a clean/verified deployment.
    """
    sha = str(approved_sha or "").strip()
    verified = _SHA_RE.fullmatch(sha) is not None
    return {
        "schemaVersion": EXPECTED_SCHEMA_VERSION,
        "surface": EXPECTED_SURFACE,
        "purpose": "public-deployment-provenance",
        "verified": verified,
        "state": "verified" if verified else "invalid_git_sha",
        "gitSha": sha if verified else "",
        "branch": "main" if verified else "",
        "clean": True if verified else None,
        "source": "remoteops-approved-git-archive" if verified else "",
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


def probe_deployment(
    canonical_url: str,
    expected_sha: str,
    *,
    opener=None,
    timeout: float = _TIMEOUT_SECONDS,
) -> dict:
    expected = str(expected_sha or "").strip()
    if not _SHA_RE.fullmatch(expected):
        return _deployment_result("expected_sha_invalid")
    try:
        url = deployment_provenance_url(canonical_url)
    except ValueError:
        return _deployment_result("canonical_url_invalid")

    client = opener or _opener()
    req = request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "CheckupAuto-Public-Deployment-Probe/1",
        },
        method="GET",
    )
    try:
        response = client.open(req, timeout=float(timeout))
        try:
            status = int(getattr(response, "status", response.getcode()))
            if status != 200:
                return _deployment_result("unexpected_status")
            content_type = str(response.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
            if content_type not in _JSON_CONTENT_TYPES:
                return _deployment_result("invalid_content_type")
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
            if len(raw) > _MAX_RESPONSE_BYTES:
                return _deployment_result("response_too_large")
            payload = json.loads(raw.decode("utf-8"))
        finally:
            try:
                response.close()
            except Exception:
                pass
    except error.HTTPError as exc:
        if 300 <= int(exc.code) < 400:
            return _deployment_result("redirected")
        if int(exc.code) == 404:
            return _deployment_result("provenance_not_found")
        return _deployment_result("http_error")
    except (error.URLError, TimeoutError, OSError):
        return _deployment_result("unavailable")
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        return _deployment_result("invalid_provenance")

    if not isinstance(payload, dict):
        return _deployment_result("invalid_provenance")
    if payload.get("schemaVersion") != EXPECTED_SCHEMA_VERSION:
        return _deployment_result("invalid_provenance")
    if payload.get("surface") != EXPECTED_SURFACE:
        return _deployment_result("surface_mismatch")
    if payload.get("purpose") != "public-deployment-provenance":
        return _deployment_result("invalid_provenance")
    actual = str(payload.get("gitSha") or "")
    if not _SHA_RE.fullmatch(actual):
        return _deployment_result("invalid_provenance")
    if payload.get("branch") != "main":
        return _deployment_result("wrong_branch")
    if payload.get("clean") is not True or payload.get("verified") is not True or payload.get("state") != "verified":
        return _deployment_result("runtime_not_clean")
    if actual != expected:
        return _deployment_result("deployment_sha_mismatch")
    return _deployment_result("verified", ok=True, sha=actual)
