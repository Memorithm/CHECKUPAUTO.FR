"""Private Payline credential loader (homologation, or gated production).

The configuration files are provisioned out-of-band on the host. This module never
creates, edits, logs or returns the merchant access key.

Production is opened only by BOTH a separate private file
(``payments/payline-production.json``, ``"environment": "production"``) AND
``CHECKUPAUTO_PAYLINE_LIVE_ENABLED=true``. Removing the variable rolls back to
homologation for new payments without a redeploy.
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import payment_payline
from payment_payline_config import PaylineSandboxConfig, PaylineConfigurationError, preflight

MAX_BYTES = 16 * 1024
DEFAULT_PATH = Path("/root/CyberCheckPrivate/payments/payline-sandbox.json")
LIVE_FLAG_ENV = "CHECKUPAUTO_PAYLINE_LIVE_ENABLED"
FILE_NAMES = {"sandbox": "payline-sandbox.json", "production": "payline-production.json"}
PATH_ENV = {"sandbox": "CYBERCHECK_PAYLINE_CONFIG_PATH", "production": "CYBERCHECK_PAYLINE_PRODUCTION_CONFIG_PATH"}


class PaylinePrivateConfigurationError(RuntimeError):
    pass


def live_enabled() -> bool:
    return str(os.environ.get(LIVE_FLAG_ENV, "")).strip() == "true"


def active_environment() -> str:
    """Environment for NEW payments; existing intents keep their own."""
    return "production" if live_enabled() else "sandbox"


def config_path(environment: str = "sandbox") -> Path:
    if environment not in FILE_NAMES:
        raise PaylinePrivateConfigurationError("payline_private_environment_invalid")
    raw = str(os.environ.get(PATH_ENV[environment]) or "").strip()
    if raw:
        path = Path(raw).expanduser()
    else:
        private = str(os.environ.get("CYBERCHECK_PRIVATE_DIR") or "").strip()
        path = (Path(private) / "payments" / FILE_NAMES[environment] if private
                else DEFAULT_PATH.with_name(FILE_NAMES[environment]))
    if not path.is_absolute():
        raise PaylinePrivateConfigurationError("payline_private_absolute_path_required")
    source = Path(__file__).resolve().parent
    try:
        inside_source = path.resolve(strict=False).is_relative_to(source)
    except OSError:
        inside_source = False
    if inside_source:
        raise PaylinePrivateConfigurationError("payline_private_outside_source_required")
    return path


def _read_json(path: Path) -> dict:
    if path.is_symlink():
        raise PaylinePrivateConfigurationError("payline_private_regular_file_required")
    try:
        info = path.stat()
    except FileNotFoundError:
        raise PaylinePrivateConfigurationError("payline_private_missing") from None
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise PaylinePrivateConfigurationError("payline_private_permissions_invalid")
    if info.st_size < 2 or info.st_size > MAX_BYTES:
        raise PaylinePrivateConfigurationError("payline_private_size_invalid")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as handle:
            raw = handle.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError
        data = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError, UnicodeError, json.JSONDecodeError):
        raise PaylinePrivateConfigurationError("payline_private_invalid") from None
    if not isinstance(data, dict):
        raise PaylinePrivateConfigurationError("payline_private_invalid")
    return data


def load(environment: str | None = None) -> PaylineSandboxConfig:
    environment = environment or active_environment()
    if environment == "production" and not live_enabled():
        raise PaylinePrivateConfigurationError("payline_live_disabled")
    try:
        config = PaylineSandboxConfig.from_mapping(_read_json(config_path(environment)))
    except PaylineConfigurationError:
        raise PaylinePrivateConfigurationError("payline_private_invalid") from None
    # A production file can never be read as homologation, nor the reverse.
    if config.environment != environment:
        raise PaylinePrivateConfigurationError("payline_private_environment_mismatch")
    return config


def status() -> dict:
    try:
        cfg = load()
    except PaylinePrivateConfigurationError as exc:
        code = str(exc)
        missing = code == "payline_private_missing"
        report = preflight(None)
        return {
            "provider": "payline",
            "environment": active_environment(),
            "configured": False,
            "configurationValid": False,
            "configurationState": "missing" if missing else "invalid",
            "credentialsVerified": False,
            "contractBindingVerified": False,
            "transportImplemented": bool(payment_payline.capability()["transportImplemented"]),
            "refundTransportImplemented": bool(payment_payline.capability().get("refundTransportImplemented")),
            "checkoutBound": bool(payment_payline.capability()["checkoutBound"]),
            "callbacksBound": bool(payment_payline.capability()["callbacksBound"]),
            "livePaymentsEnabled": False,
            "ready": False,
            "blockingReasons": list(report["blockingReasons"]),
        }
    report = preflight(cfg)
    return {
        "provider": "payline",
        "environment": active_environment(),
        "configured": True,
        "configurationValid": True,
        "configurationState": "configured_unverified",
        "credentialsVerified": bool(report["credentialsVerified"]),
        "contractBindingVerified": bool(report["contractBindingVerified"]),
        "transportImplemented": bool(payment_payline.capability()["transportImplemented"]),
        "refundTransportImplemented": bool(payment_payline.capability().get("refundTransportImplemented")),
        "checkoutBound": bool(payment_payline.capability()["checkoutBound"]),
        "callbacksBound": bool(payment_payline.capability()["callbacksBound"]),
        "livePaymentsEnabled": cfg.environment == "production",
        "ready": False,
        "blockingReasons": list(report["blockingReasons"]),
    }
