"""Private admin writer for customer OIDC provider credentials."""
from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

import customer_oidc


class CustomerOIDCAdminError(ValueError):
    pass


def _clean_text(value: object, *, minimum: int, maximum: int, code: str) -> str:
    if not isinstance(value, str):
        raise CustomerOIDCAdminError(code)
    raw = value.strip()
    if not minimum <= len(raw) <= maximum or any(ord(ch) < 32 or ord(ch) == 127 for ch in raw):
        raise CustomerOIDCAdminError(code)
    return raw


def _provider(value: object) -> str:
    raw = str(value or "").strip().lower()
    if raw not in customer_oidc.PROVIDERS:
        raise CustomerOIDCAdminError("customer_oidc_admin_provider_invalid")
    return raw


def _path() -> Path:
    path = customer_oidc._config_path()
    if not path.is_absolute():
        raise CustomerOIDCAdminError("customer_oidc_admin_path_invalid")
    return path


def _read_document() -> dict:
    path = _path()
    if path.is_symlink():
        raise CustomerOIDCAdminError("customer_oidc_admin_target_invalid")
    if not path.exists():
        return {"providers": {}}
    try:
        doc = customer_oidc._load_config()
    except customer_oidc.CustomerOIDCError:
        raise CustomerOIDCAdminError("customer_oidc_admin_existing_config_invalid") from None
    providers = doc.get("providers")
    if not isinstance(providers, dict):
        raise CustomerOIDCAdminError("customer_oidc_admin_existing_config_invalid")
    # Preserve only known provider records. Unknown records could hide accidental
    # secrets under a provider the runtime will never consume.
    if set(providers) - set(customer_oidc.PROVIDERS):
        raise CustomerOIDCAdminError("customer_oidc_admin_existing_config_invalid")
    return {"providers": dict(providers)}


def _write(doc: dict) -> None:
    path = _path()
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    try:
        parent.chmod(0o700)
    except OSError:
        raise CustomerOIDCAdminError("customer_oidc_admin_private_dir_invalid") from None
    if path.exists() and path.is_symlink():
        raise CustomerOIDCAdminError("customer_oidc_admin_target_invalid")
    raw = (json.dumps(doc, ensure_ascii=True, separators=(",", ":")) + "\n").encode("utf-8")
    if len(raw) > customer_oidc.MAX_CONFIG_BYTES:
        raise CustomerOIDCAdminError("customer_oidc_admin_config_too_large")
    tmp = parent / f".{path.name}.{secrets.token_hex(8)}.tmp"
    fd = None
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb", closefd=True) as handle:
            fd = None
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        directory = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError:
        if fd is not None:
            os.close(fd)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise CustomerOIDCAdminError("customer_oidc_admin_write_failed") from None


def status(public_origin: str) -> dict:
    origin = customer_oidc._origin(public_origin)
    return {
        "providers": [
            {
                **item,
                "callbackUrl": f"{origin}/auth/customer/{item['id']}/callback",
            }
            for item in customer_oidc.provider_status()
        ],
        "secretsReadable": False,
    }


def save(provider: object, client_id: object, client_secret: object, public_origin: str) -> dict:
    provider = _provider(provider)
    client_id = _clean_text(
        client_id, minimum=1, maximum=512, code="customer_oidc_admin_client_id_invalid"
    )
    client_secret = _clean_text(
        client_secret, minimum=8, maximum=4096, code="customer_oidc_admin_client_secret_invalid"
    )
    # Validate the origin now; callback URLs are derived by the runtime and never
    # accepted from the browser.
    origin = customer_oidc._origin(public_origin)
    doc = _read_document()
    doc["providers"][provider] = {
        "clientId": client_id,
        "clientSecret": client_secret,
    }
    _write(doc)
    configured = {row["id"]: row["configured"] for row in customer_oidc.provider_status()}
    if configured.get(provider) is not True:
        raise CustomerOIDCAdminError("customer_oidc_admin_verify_failed")
    return {
        "provider": provider,
        "configured": True,
        "callbackUrl": f"{origin}/auth/customer/{provider}/callback",
        "secretsReadable": False,
    }


def remove(provider: object, public_origin: str) -> dict:
    provider = _provider(provider)
    origin = customer_oidc._origin(public_origin)
    doc = _read_document()
    existed = provider in doc["providers"]
    doc["providers"].pop(provider, None)
    _write(doc)
    configured = {row["id"]: row["configured"] for row in customer_oidc.provider_status()}
    if configured.get(provider):
        raise CustomerOIDCAdminError("customer_oidc_admin_remove_verify_failed")
    return {
        "provider": provider,
        "configured": False,
        "removed": existed,
        "callbackUrl": f"{origin}/auth/customer/{provider}/callback",
        "secretsReadable": False,
    }
