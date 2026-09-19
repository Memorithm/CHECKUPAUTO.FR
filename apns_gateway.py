from __future__ import annotations

import base64
import json
import os
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
TRANSIENT_REASONS = {"InternalServerError", "ServiceUnavailable", "Shutdown", "TooManyRequests", "TooManyProviderTokenUpdates", "TransportError"}
TRANSIENT_STATUS = {429, 500, 503}


class APNSError(RuntimeError):
    def __init__(self, status: int, reason: str, *, apns_id: str = "", retry_after: str = ""):
        self.status = int(status)
        self.reason = str(reason or "APNs error")[:120]
        self.apns_id = str(apns_id or "")[:80]
        self.retry_after = str(retry_after or "")[:80]
        self.token_invalid = self.status == 410 or self.reason in TOKEN_INVALID_REASONS
        self.provider_error = self.reason in PROVIDER_CONFIGURATION_REASONS or self.status in {403, 404, 405}
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


def _provider_token(cfg: dict) -> str:
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    except ImportError as exc:
        raise RuntimeError("cryptography indisponible pour APNs") from exc
    header = _b64(json.dumps({"alg":"ES256","kid":cfg["keyId"]}, separators=(",", ":")).encode())
    claims = _b64(json.dumps({"iss":cfg["teamId"],"iat":int(time.time())}, separators=(",", ":")).encode())
    signing_input = f"{header}.{claims}".encode("ascii")
    key = serialization.load_pem_private_key(Path(cfg["keyPath"]).read_bytes(), password=None)
    der = key.sign(signing_input, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    return f"{header}.{claims}.{_b64(signature)}"


def _error_from_response(response) -> APNSError:
    reason = "APNs error"
    try:
        payload = response.json()
        if isinstance(payload, dict):
            reason = str(payload.get("reason") or reason)
    except Exception:
        pass
    return APNSError(
        response.status_code,
        reason,
        apns_id=response.headers.get("apns-id", ""),
        retry_after=response.headers.get("retry-after", ""),
    )


def send(device_token: str, title: str, body: str, *, data: dict | None = None, environment: str = "sandbox") -> dict:
    cfg = _config()
    if not status()["configured"]:
        raise RuntimeError("APNs non configuré")
    try:
        import httpx
    except ImportError as exc:
        raise RuntimeError("httpx indisponible pour APNs") from exc
    environment = str(environment or "sandbox").strip().lower()
    if environment not in {"sandbox", "production"}:
        raise ValueError("Environnement APNs invalide")
    host = "https://api.push.apple.com" if environment == "production" else "https://api.sandbox.push.apple.com"
    payload = {"aps": {"alert": {"title": str(title)[:120], "body": str(body)[:500]}, "sound": "default"}}
    if data:
        payload["data"] = data
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(raw) > 4096:
        raise ValueError("payload APNs trop volumineux")
    headers = {"authorization": f"bearer {_provider_token(cfg)}", "apns-topic": cfg["topic"],
               "apns-push-type": "alert", "apns-priority": "10", "content-type": "application/json"}
    try:
        with httpx.Client(http2=True, timeout=12.0) as client:
            response = client.post(f"{host}/3/device/{device_token}", content=raw, headers=headers)
    except httpx.RequestError as exc:
        raise APNSError(0, "TransportError") from exc
    if response.status_code != 200:
        raise _error_from_response(response)
    return {"ok": True, "status": 200, "apnsId": response.headers.get("apns-id", "")}
