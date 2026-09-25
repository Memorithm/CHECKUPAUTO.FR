"""Admin-only writer for Payline / Monext sandbox credentials.

This module writes the sandbox API configuration to the private runtime volume.
Secrets are never returned by any function in this module.
"""
from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

import payment_payline_private as private
from payment_payline_config import PaylineSandboxConfig, PaylineConfigurationError


class PaylineSandboxAdminError(ValueError):
    pass


def _payload(values: dict, public_origin: str) -> dict:
    if not isinstance(values, dict) or set(values) != {"merchantId", "accessKey", "contractNumber"}:
        raise PaylineSandboxAdminError("payline_sandbox_admin_payload_invalid")
    document = {
        "environment": "sandbox",
        "merchantId": values.get("merchantId"),
        "accessKey": values.get("accessKey"),
        "contractNumber": values.get("contractNumber"),
        "publicOrigin": public_origin,
    }
    try:
        cfg = PaylineSandboxConfig.from_mapping(document)
    except PaylineConfigurationError:
        raise PaylineSandboxAdminError("payline_sandbox_admin_configuration_invalid") from None
    return {
        "environment": cfg.environment,
        "merchantId": cfg.merchant_id,
        "accessKey": cfg.access_key,
        "contractNumber": cfg.contract_number,
        "publicOrigin": cfg.public_origin,
    }


def save(values: dict, public_origin: str) -> dict:
    document = _payload(values, public_origin)
    path = private.config_path()
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    try:
        parent.chmod(0o700)
    except OSError:
        raise PaylineSandboxAdminError("payline_sandbox_admin_private_dir_invalid") from None
    if path.exists() and path.is_symlink():
        raise PaylineSandboxAdminError("payline_sandbox_admin_target_invalid")

    tmp = parent / f".{path.name}.{secrets.token_hex(8)}.tmp"
    raw = (json.dumps(document, ensure_ascii=True, separators=(",", ":")) + "\n").encode("utf-8")
    if len(raw) > private.MAX_BYTES:
        raise PaylineSandboxAdminError("payline_sandbox_admin_configuration_invalid")

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
        try:
            dfd = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        except OSError:
            pass
    except OSError:
        if fd is not None:
            os.close(fd)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise PaylineSandboxAdminError("payline_sandbox_admin_write_failed") from None

    status = private.status()
    if not status.get("configured") or not status.get("configurationValid"):
        raise PaylineSandboxAdminError("payline_sandbox_admin_verify_failed")
    return {
        "provider": "payline",
        "environment": "sandbox",
        "configured": True,
        "configurationValid": True,
        "checkoutBound": bool(status.get("checkoutBound")),
        "callbacksBound": bool(status.get("callbacksBound")),
        "livePaymentsEnabled": False,
    }
