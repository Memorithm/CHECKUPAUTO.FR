"""Authenticated administration for customer OIDC providers."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import time
from pathlib import Path
from urllib.parse import urlsplit

import customer_oidc_admin

ROUTE = "/api/admin/customers/oidc"
MAX_BODY = 16384


def _csrf_key_path() -> Path:
    return Path(os.environ.get("CYBERCHECK_PRIVATE_DIR", "/root/CyberCheckPrivate")) / "admin" / "csrf.key"


def csrf_secret() -> str:
    """Dedicated random CSRF key, independent of the admin password (audit S-07)."""
    path = _csrf_key_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except PermissionError:
        pass
    if not path.exists() and not path.is_symlink():
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            fd = -1
        if fd >= 0:
            with os.fdopen(fd, "wb") as handle:
                handle.write(secrets.token_bytes(32))
                handle.flush()
                os.fsync(handle.fileno())
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as handle:
        key = handle.read(33)
    if len(key) != 32:
        raise RuntimeError("admin_csrf_key_invalid")
    return key.hex()


def csrf_token(secret: str, headers, hour: int | None = None) -> str:
    period = int(time.time() // 3600) if hour is None else int(hour)
    binding = hashlib.sha256(
        (
            str(headers.get("Authorization", ""))
            + "\x00"
            + str(headers.get("Cookie", ""))
        ).encode("utf-8")
    ).hexdigest()
    return hmac.new(
        secret.encode("utf-8"),
        f"customer-oidc-admin:{period}:{binding}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _strict_json(raw: bytes) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate")
            result[key] = value
        return result
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    except (ValueError, UnicodeError, RecursionError):
        raise ValueError("invalid") from None
    if not isinstance(value, dict):
        raise ValueError("object")
    return value


def handle(handler, *, secret: str) -> bool:
    parsed = urlsplit(handler.path)
    if parsed.path != ROUTE:
        return False

    def reject(code: str, status: int):
        handler.send_json({"ok": False, "error": code}, status)
        return True

    if not handler.authorized():
        handler.require_auth()
        return True
    if not handler._mfa_session_valid():
        handler.require_mfa()
        return True
    if parsed.query or parsed.fragment:
        return reject("customer_oidc_admin_query_not_allowed", 400)

    host = str(handler.headers.get("Host") or "").strip().lower()
    if (
        not host
        or len(host) > 255
        or "/" in host
        or "@" in host
        or not re.fullmatch(r"[A-Za-z0-9.-]+(?::[0-9]{1,5})?", host)
    ):
        return reject("customer_oidc_admin_origin_invalid", 400)
    origin = "https://" + host

    if handler.command == "GET":
        try:
            handler.send_json({
                "ok": True,
                **customer_oidc_admin.status(origin),
                "csrfToken": csrf_token(secret, handler.headers),
            })
        except Exception:
            return reject("customer_oidc_admin_status_unavailable", 500)
        return True

    if handler.command != "POST":
        return reject("customer_oidc_admin_method_not_allowed", 405)
    if not handler._admin_origin_ok() or handler.headers.get("Sec-Fetch-Site", "") == "cross-site":
        return reject("customer_oidc_admin_origin_not_allowed", 403)

    supplied = str(handler.headers.get("X-CheckupAuto-Customer-OIDC-CSRF") or "")
    current = int(time.time() // 3600)
    if not re.fullmatch(r"[0-9a-f]{64}", supplied) or not any(
        hmac.compare_digest(supplied, csrf_token(secret, handler.headers, hour))
        for hour in (current, current - 1)
    ):
        return reject("customer_oidc_admin_csrf_invalid", 403)
    if handler.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
        return reject("customer_oidc_admin_content_type_invalid", 415)
    if handler.headers.get("Transfer-Encoding"):
        return reject("customer_oidc_admin_transfer_encoding_invalid", 400)
    try:
        length = int(handler.headers.get("Content-Length", ""))
    except (ValueError, TypeError):
        return reject("customer_oidc_admin_content_length_invalid", 400)
    if not 1 <= length <= MAX_BODY:
        return reject("customer_oidc_admin_body_too_large", 413)
    raw = handler.rfile.read(length)
    if len(raw) != length:
        return reject("customer_oidc_admin_payload_invalid", 400)

    try:
        payload = _strict_json(raw)
        action = payload.get("action")
        if action == "save" and set(payload) == {"action", "provider", "clientId", "clientSecret"}:
            result = customer_oidc_admin.save(
                payload.get("provider"),
                payload.get("clientId"),
                payload.get("clientSecret"),
                origin,
            )
        elif action == "remove" and set(payload) == {"action", "provider"}:
            result = customer_oidc_admin.remove(payload.get("provider"), origin)
        else:
            return reject("customer_oidc_admin_payload_invalid", 400)
        handler.send_json({
            "ok": True,
            **result,
            "csrfToken": csrf_token(secret, handler.headers),
        }, 200 if action == "remove" else 201)
    except ValueError:
        return reject("customer_oidc_admin_payload_invalid", 400)
    except customer_oidc_admin.CustomerOIDCAdminError as exc:
        code = str(exc)
        invalid = {
            "customer_oidc_admin_provider_invalid",
            "customer_oidc_admin_client_id_invalid",
            "customer_oidc_admin_client_secret_invalid",
            "customer_oidc_admin_target_invalid",
            "customer_oidc_admin_existing_config_invalid",
            "customer_oidc_admin_path_invalid",
        }
        return reject(code if code in invalid else "customer_oidc_admin_unavailable", 400 if code in invalid else 500)
    except Exception:
        return reject("customer_oidc_admin_unavailable", 500)
    return True
