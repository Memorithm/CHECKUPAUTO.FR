from __future__ import annotations

import base64
import json
import os
import re
import time
from pathlib import Path

PRIVATE_DIR = Path(os.environ.get("CYBERCHECK_PRIVATE_DIR", "/root/CyberCheckPrivate"))
DEFAULT_TOPIC = "fr.checkupauto.reminder"

TOKEN_INVALID_REASONS = {"BadDeviceToken", "Unregistered"}
PROVIDER_CONFIGURATION_REASONS = {
    "BadCertificate", "BadCertificateEnvironment", "BadTopic", "DeviceTokenNotForTopic",
    "ExpiredProviderToken", "Forbidden", "InvalidProviderToken", "MissingProviderToken",
    "MissingTopic", "TopicDisallowed",
}
INTERNAL_CONFIGURATION_REASONS = {"CredentialsMissing", "RuntimeDependencyMissing", "SigningKeyInvalid"}
PROVIDER_REQUEST_REASONS = {
    "BadCollapseId", "BadExpirationDate", "BadMessageId", "BadPath", "BadPriority",
    "DuplicateHeaders", "MethodNotAllowed", "MissingDeviceToken", "PayloadEmpty", "PayloadTooLarge",
}
INTERNAL_REQUEST_REASONS = {"CategoryInvalid", "EnvironmentInvalid", "PayloadInvalid"}
TRANSIENT_REASONS = {
    "IdleTimeout", "InternalServerError", "ServiceUnavailable", "Shutdown", "TooManyRequests",
    "TooManyProviderTokenUpdates", "TransportError",
}
TRANSIENT_STATUS = {429, 500, 503}
REQUEST_STATUS = {400, 404, 405, 413}
KNOWN_PROVIDER_REASONS = (
    TOKEN_INVALID_REASONS | PROVIDER_CONFIGURATION_REASONS | PROVIDER_REQUEST_REASONS | TRANSIENT_REASONS
)
KNOWN_ERROR_REASONS = KNOWN_PROVIDER_REASONS | INTERNAL_CONFIGURATION_REASONS | INTERNAL_REQUEST_REASONS
REQUEST_REASONS = PROVIDER_REQUEST_REASONS | INTERNAL_REQUEST_REASONS
UNKNOWN_PROVIDER_REASON = "UnknownProviderError"


class APNSError(RuntimeError):
    def __init__(self, status: int, reason: str, *, apns_id: str = "", retry_after: str = ""):
        self.status = int(status)
        raw_reason = str(reason or "").strip()
        self.reason = raw_reason if raw_reason in KNOWN_ERROR_REASONS else UNKNOWN_PROVIDER_REASON
        raw_apns_id = str(apns_id or "").strip()
        self.apns_id = raw_apns_id if re.fullmatch(r"[0-9A-Fa-f-]{1,80}", raw_apns_id) else ""
        raw_retry_after = str(retry_after or "").strip()
        self.retry_after = raw_retry_after if re.fullmatch(r"[0-9]{1,10}", raw_retry_after) else ""
        self.token_invalid = self.status == 410 or self.reason in TOKEN_INVALID_REASONS
        self.provider_error = self.reason in (PROVIDER_CONFIGURATION_REASONS | INTERNAL_CONFIGURATION_REASONS) or self.status == 403
        self.request_error = self.reason in REQUEST_REASONS or (
            self.status in REQUEST_STATUS and self.reason not in TRANSIENT_REASONS
        )
        self.retryable = self.status in TRANSIENT_STATUS or self.reason in TRANSIENT_REASONS
        super().__init__(f"APNs {self.status}: {self.reason}")


def _read_private(name: str, env: str = "") -> str:
    value = str(os.environ.get(env, "") or "").strip() if env else ""
    if value:
        return value
    path = PRIVATE_DIR / name
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def _config() -> dict:
    return {
        "keyId": _read_private("apns-key-id", "CYBERCHECK_APNS_KEY_ID"),
        "teamId": _read_private("apns-team-id", "CYBERCHECK_APNS_TEAM_ID"),
        "keyPath": str(PRIVATE_DIR / "apns-key.p8"),
        "topic": str(os.environ.get("CYBERCHECK_APNS_TOPIC", DEFAULT_TOPIC) or DEFAULT_TOPIC).strip(),
    }


def status() -> dict:
    cfg = _config()
    try:
        key_exists = Path(cfg["keyPath"]).is_file()
    except OSError:
        key_exists = False
    configured = bool(cfg["keyId"] and cfg["teamId"] and cfg["topic"] and key_exists)
    return {"configured": configured, "transport": "apns-http2", "state": "ready" if configured else "awaiting_credentials",
            "environments": ["sandbox", "production"], "topic": cfg["topic"], "keyPresent": key_exists,
            "keyIdPresent": bool(cfg["keyId"]), "teamIdPresent": bool(cfg["teamId"])}


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _load_signing_key(path: str):
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
    except ImportError as exc:
        raise RuntimeError("cryptography indisponible pour APNs") from exc
    key = serialization.load_pem_private_key(Path(path).read_bytes(), password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
        raise ValueError("La clé APNs doit être une clé privée EC P-256")
    return key


def _provider_token(cfg: dict) -> str:
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    except ImportError as exc:
        raise RuntimeError("cryptography indisponible pour APNs") from exc
    header = _b64(json.dumps({"alg":"ES256","kid":cfg["keyId"]}, separators=(",", ":")).encode())
    claims = _b64(json.dumps({"iss":cfg["teamId"],"iat":int(time.time())}, separators=(",", ":")).encode())
    signing_input = f"{header}.{claims}".encode("ascii")
    key = _load_signing_key(cfg["keyPath"])
    der = key.sign(signing_input, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    return f"{header}.{claims}.{_b64(signature)}"


def preflight() -> dict:
    """Validate APNs credentials locally without sending a push notification."""
    cfg = _config()
    static = status()
    if not static["configured"]:
        return {**static, "ready": False, "state": "awaiting_credentials", "reason": "credentials_missing", "keyValid": False}
    if len(cfg["keyId"]) != 10 or not cfg["keyId"].isalnum():
        return {**static, "configured": False, "ready": False, "state": "invalid_configuration", "reason": "key_id_invalid", "keyValid": False}
    if len(cfg["teamId"]) != 10 or not cfg["teamId"].isalnum():
        return {**static, "configured": False, "ready": False, "state": "invalid_configuration", "reason": "team_id_invalid", "keyValid": False}
    if not cfg["topic"] or len(cfg["topic"]) > 255 or any(ch.isspace() for ch in cfg["topic"]):
        return {**static, "configured": False, "ready": False, "state": "invalid_configuration", "reason": "topic_invalid", "keyValid": False}
    try:
        _load_signing_key(cfg["keyPath"])
        token = _provider_token(cfg)
        if token.count(".") != 2:
            raise ValueError("JWT APNs invalide")
    except PermissionError:
        return {**static, "configured": False, "ready": False, "state": "invalid_configuration", "reason": "key_unreadable", "keyValid": False}
    except OSError:
        return {**static, "configured": False, "ready": False, "state": "invalid_configuration", "reason": "key_unreadable", "keyValid": False}
    except (ValueError, RuntimeError):
        return {**static, "configured": False, "ready": False, "state": "invalid_configuration", "reason": "key_invalid", "keyValid": False}
    return {**static, "ready": True, "state": "ready", "reason": "local_signing_validated", "keyValid": True}


def _provider_reason(value: object) -> str:
    raw = str(value or "").strip()
    return raw if raw in KNOWN_PROVIDER_REASONS else UNKNOWN_PROVIDER_REASON


def _apns_id(value: object) -> str:
    raw = str(value or "").strip()
    if re.fullmatch(r"[0-9A-Fa-f-]{1,80}", raw):
        return raw
    return ""


def _retry_after(value: object) -> str:
    raw = str(value or "").strip()
    return raw if re.fullmatch(r"[0-9]{1,10}", raw) else ""


def _error_from_response(response) -> APNSError:
    reason = UNKNOWN_PROVIDER_REASON
    try:
        payload = response.json()
        if isinstance(payload, dict):
            reason = _provider_reason(payload.get("reason"))
    except Exception:
        pass
    headers = getattr(response, "headers", {}) or {}
    return APNSError(
        response.status_code,
        reason,
        apns_id=_apns_id(headers.get("apns-id", "")),
        retry_after=_retry_after(headers.get("retry-after", "")),
    )


def _notification_payload(
    title: str,
    body: str,
    *,
    data: dict | None = None,
    notification_category: str = "",
) -> dict:
    aps = {"alert": {"title": str(title)[:120], "body": str(body)[:500]}, "sound": "default"}
    category = str(notification_category or "").strip()
    if category:
        if len(category) > 64 or not re.fullmatch(r"[A-Za-z0-9._-]+", category):
            raise APNSError(0, "CategoryInvalid")
        aps["category"] = category
    payload = {"aps": aps}
    if data:
        payload["data"] = data
    return payload


def _environment_host(value: object) -> tuple[str, str]:
    environment = str(value or "sandbox").strip().lower()
    if environment not in {"sandbox", "production"}:
        raise APNSError(0, "EnvironmentInvalid")
    host = "https://api.push.apple.com" if environment == "production" else "https://api.sandbox.push.apple.com"
    return environment, host


def _encoded_payload(
    title: str,
    body: str,
    *,
    data: dict | None = None,
    notification_category: str = "",
) -> bytes:
    payload = _notification_payload(
        title,
        body,
        data=data,
        notification_category=notification_category,
    )
    try:
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise APNSError(0, "PayloadInvalid") from exc
    if len(raw) > 4096:
        raise APNSError(413, "PayloadTooLarge")
    return raw


def send(
    device_token: str,
    title: str,
    body: str,
    *,
    data: dict | None = None,
    environment: str = "sandbox",
    notification_category: str = "",
) -> dict:
    environment, host = _environment_host(environment)
    raw = _encoded_payload(
        title,
        body,
        data=data,
        notification_category=notification_category,
    )
    cfg = _config()
    if not status()["configured"]:
        raise APNSError(0, "CredentialsMissing")
    try:
        import httpx
    except ImportError as exc:
        raise APNSError(0, "RuntimeDependencyMissing") from exc
    try:
        provider_token = _provider_token(cfg)
    except APNSError:
        raise
    except (OSError, ValueError, TypeError, RuntimeError) as exc:
        raise APNSError(0, "SigningKeyInvalid") from exc
    headers = {"authorization": f"bearer {provider_token}", "apns-topic": cfg["topic"],
               "apns-push-type": "alert", "apns-priority": "10", "content-type": "application/json"}
    try:
        with httpx.Client(http2=True, timeout=12.0) as client:
            response = client.post(f"{host}/3/device/{device_token}", content=raw, headers=headers)
    except httpx.RequestError as exc:
        raise APNSError(0, "TransportError") from exc
    if response.status_code != 200:
        raise _error_from_response(response)
    return {"ok": True, "status": 200, "apnsId": _apns_id(response.headers.get("apns-id", ""))}
