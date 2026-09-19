from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path

PRIVATE_DIR = Path(os.environ.get("CYBERCHECK_PRIVATE_DIR", "/root/CyberCheckPrivate"))
DEFAULT_TOPIC = "fr.checkupauto.reminder"


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
    cfg = _config(); key_exists = Path(cfg["keyPath"]).is_file()
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
    with httpx.Client(http2=True, timeout=12.0) as client:
        response = client.post(f"{host}/3/device/{device_token}", content=raw, headers=headers)
    if response.status_code != 200:
        reason = "APNs error"
        try:
            reason = str(response.json().get("reason") or reason)[:120]
        except Exception:
            pass
        raise RuntimeError(f"APNs {response.status_code}: {reason}")
    return {"ok": True, "status": 200, "apnsId": response.headers.get("apns-id", "")}
