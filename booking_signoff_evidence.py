"""Signed production sign-off for the on-site booking journey.

Read-only verifier: this module never creates, signs or writes evidence at
runtime.  An operator produces the sign-off document outside the web process
after the step5 (customer journey) and step6 (production sign-off) checklists
and the activation checklist have been satisfied, then signs it with HMAC-SHA256
using a private key that only the server can read.

Without a present, authentic, unexpired document bound to the configured
Mercure line/operator, every capability evaluates to False.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import re
import stat
from pathlib import Path

import customer_booking_activation_evidence
import mercure_step5_customer_journey
import mercure_step6_production_signoff

SCHEMA = "checkupauto.booking-signoff/v1"
FILE_ENV = "CHECKUPAUTO_BOOKING_SIGNOFF_FILE"
KEY_FILE_ENV = "CHECKUPAUTO_BOOKING_SIGNOFF_KEY_FILE"
DEFAULT_FILE_NAME = "booking-signoff.json"
DEFAULT_KEY_NAME = "booking-signoff.key"
MAX_VALIDITY_DAYS = 90
MAX_DOCUMENT_BYTES = 64 * 1024
MIN_KEY_BYTES = 32
FIELDS = frozenset({"schema", "issuedAt", "expiresAt", "approvedBy", "provider",
                    "step5", "step6", "activation", "signature"})


class BookingSignoffError(ValueError):
    pass


def _private_dir(environ) -> Path:
    return Path(environ.get("CYBERCHECK_PRIVATE_DIR", "/root/CyberCheckPrivate"))


def paths(environ=None) -> tuple[Path, Path]:
    source = os.environ if environ is None else environ
    private = _private_dir(source)
    document = source.get(FILE_ENV, "").strip() or str(private / DEFAULT_FILE_NAME)
    key = source.get(KEY_FILE_ENV, "").strip() or str(private / DEFAULT_KEY_NAME)
    return Path(document), Path(key)


def canonical_bytes(document: dict) -> bytes:
    """Bytes covered by the signature: every field except ``signature``."""
    if not isinstance(document, dict):
        raise BookingSignoffError("booking_signoff_invalid")
    body = {key: value for key, value in document.items() if key != "signature"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def compute_signature(document: dict, key: bytes) -> str:
    if not isinstance(key, bytes) or len(key) < MIN_KEY_BYTES:
        raise BookingSignoffError("booking_signoff_key_invalid")
    return hmac.new(key, canonical_bytes(document), hashlib.sha256).hexdigest()


def _timestamp(value: object) -> dt.datetime:
    if not isinstance(value, str) or not value.strip():
        raise BookingSignoffError("booking_signoff_dates_invalid")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BookingSignoffError("booking_signoff_dates_invalid") from exc
    if parsed.tzinfo is None:
        raise BookingSignoffError("booking_signoff_dates_invalid")
    return parsed


def verify(document: object, *, key: bytes, line_id: str, operator_id: str,
           now: dt.datetime | None = None) -> dict:
    """Return ``{"valid": True, ...}`` or raise :class:`BookingSignoffError`."""
    if not isinstance(document, dict) or set(document) != FIELDS:
        raise BookingSignoffError("booking_signoff_invalid")
    if document["schema"] != SCHEMA:
        raise BookingSignoffError("booking_signoff_schema_invalid")
    signature = document["signature"]
    if not isinstance(signature, str) or not re.fullmatch(r"[0-9a-f]{64}", signature):
        raise BookingSignoffError("booking_signoff_signature_invalid")
    expected = compute_signature(document, key)
    if not hmac.compare_digest(expected, signature):
        raise BookingSignoffError("booking_signoff_signature_invalid")
    issued = _timestamp(document["issuedAt"])
    expires = _timestamp(document["expiresAt"])
    current = now or dt.datetime.now(dt.timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=dt.timezone.utc)
    if not issued < expires or expires - issued > dt.timedelta(days=MAX_VALIDITY_DAYS):
        raise BookingSignoffError("booking_signoff_dates_invalid")
    if current < issued:
        raise BookingSignoffError("booking_signoff_not_yet_valid")
    if current >= expires:
        raise BookingSignoffError("booking_signoff_expired")
    approver = document["approvedBy"]
    if not isinstance(approver, str) or not approver.strip() or len(approver) > 120:
        raise BookingSignoffError("booking_signoff_approver_missing")
    provider = document["provider"]
    if (not isinstance(provider, dict) or set(provider) != {"lineId", "operatorId"}
            or provider.get("lineId") != line_id or provider.get("operatorId") != operator_id
            or not re.fullmatch(r"[0-9]{1,12}", str(line_id or ""))
            or not re.fullmatch(r"[0-9]{1,12}", str(operator_id or ""))):
        raise BookingSignoffError("booking_signoff_provider_mismatch")
    for name, check, flag in (
        ("step5", mercure_step5_customer_journey.evaluate, "passed"),
        ("step6", mercure_step6_production_signoff.assess, "approved"),
        ("activation", customer_booking_activation_evidence.assess, "eligible"),
    ):
        section = document[name]
        if not isinstance(section, dict) or not all(type(v) is bool for v in section.values()):
            raise BookingSignoffError(f"booking_signoff_{name}_invalid")
        try:
            result = check(section)
        except ValueError as exc:
            raise BookingSignoffError(f"booking_signoff_{name}_invalid") from exc
        if result.get(flag) is not True:
            raise BookingSignoffError(f"booking_signoff_{name}_incomplete")
    return {"valid": True, "approvedBy": approver.strip(),
            "expiresAt": expires.isoformat(timespec="seconds")}


def _read_key(path: Path) -> bytes:
    try:
        info = path.stat()
    except FileNotFoundError as exc:
        raise BookingSignoffError("booking_signoff_key_missing") from exc
    if not stat.S_ISREG(info.st_mode):
        raise BookingSignoffError("booking_signoff_key_invalid")
    if os.name == "posix" and info.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise BookingSignoffError("booking_signoff_key_permissions_invalid")
    key = path.read_bytes().strip()
    if len(key) < MIN_KEY_BYTES:
        raise BookingSignoffError("booking_signoff_key_invalid")
    return key


def _read_document(path: Path) -> object:
    try:
        info = path.stat()
    except FileNotFoundError as exc:
        raise BookingSignoffError("booking_signoff_missing") from exc
    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_DOCUMENT_BYTES:
        raise BookingSignoffError("booking_signoff_invalid")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise BookingSignoffError("booking_signoff_invalid") from exc


def status(*, line_id: str, operator_id: str, environ=None,
           now: dt.datetime | None = None) -> dict:
    """Non-sensitive verification state; never raises, never writes."""
    document_path, key_path = paths(environ)
    try:
        document = _read_document(document_path)
        key = _read_key(key_path)
        result = verify(document, key=key, line_id=line_id,
                        operator_id=operator_id, now=now)
    except BookingSignoffError as exc:
        return {"valid": False, "reason": str(exc)}
    except OSError:
        return {"valid": False, "reason": "booking_signoff_unreadable"}
    return {"valid": True, "reason": "", "expiresAt": result["expiresAt"]}
