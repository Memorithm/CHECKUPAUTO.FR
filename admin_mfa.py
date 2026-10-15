from __future__ import annotations

import base64
from contextlib import contextmanager
import fcntl
from io import BytesIO
import hashlib
import hmac
from http.cookies import SimpleCookie
import json
import os
from pathlib import Path
import re
import secrets
import struct
import tempfile
import threading
import time
from urllib.parse import quote, urlencode

import qrcode
from qrcode.image.svg import SvgPathImage


COOKIE_NAME = "CyberCheckAdmin2FAV2"
SESSION_TTL_SECONDS = 2 * 3600
REQUIRED_ENV = "CYBERCHECK_ADMIN_MFA_REQUIRED"
_STATE_LOCK = threading.RLock()
PENDING_TTL_SECONDS = 15 * 60
TOTP_PERIOD_SECONDS = 30
TOTP_DIGITS = 6
TOTP_WINDOW = 1
_RECOVERY_COUNT = 10
_RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CODE_RE = re.compile(r"^[0-9]{6}$")
_RECOVERY_RE = re.compile(r"^[A-Z2-9]{12}$")


def _private_dir() -> Path:
    return Path(
        os.environ.get("CYBERCHECK_PRIVATE_DIR", "/root/CyberCheckPrivate")
    ).expanduser()


def _mfa_dir() -> Path:
    raw = str(os.environ.get("CYBERCHECK_ADMIN_MFA_DIR") or "").strip()
    return Path(raw).expanduser() if raw else _private_dir() / "admin-mfa"


def _secret_path() -> Path:
    return _mfa_dir() / "totp-secret"


def _pending_path() -> Path:
    return _mfa_dir() / "totp-pending.json"


def _session_key_path() -> Path:
    return _mfa_dir() / "session-hmac-key"


def _recovery_path() -> Path:
    return _mfa_dir() / "recovery.json"


def _last_step_path() -> Path:
    return _mfa_dir() / "totp-last-step"


def _revoked_path() -> Path:
    return _mfa_dir() / "revoked-sessions.json"


def required() -> bool:
    """Opt-in: refuse admin APIs until a TOTP is enrolled (see docs/admin-2fa.md)."""
    return str(os.environ.get(REQUIRED_ENV) or "").strip().lower() in {"1", "true", "yes"}


@contextmanager
def _state_lock():
    """Serialise read-modify-write of MFA state across threads and processes."""
    with _STATE_LOCK:
        root = _ensure_dir()
        fd = os.open(root / ".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


def _ensure_dir() -> Path:
    root = _mfa_dir()
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(0o700)
    return root


def _atomic_write(path: Path, data: bytes, mode: int = 0o600) -> None:
    root = _ensure_dir()
    if path.parent.resolve() != root.resolve():
        raise RuntimeError("chemin MFA invalide")
    fd, temporary = tempfile.mkstemp(prefix=".mfa-", dir=root)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        path.chmod(mode)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _b32_decode(secret: str) -> bytes:
    raw = str(secret or "").strip().upper()
    if not raw or not re.fullmatch(r"[A-Z2-7]{16,128}", raw):
        raise ValueError("secret TOTP invalide")
    padding = "=" * ((8 - len(raw) % 8) % 8)
    return base64.b32decode(raw + padding, casefold=False)


def generate_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def totp_at(
    secret: str,
    timestamp: int | float,
    *,
    digits: int = TOTP_DIGITS,
    period: int = TOTP_PERIOD_SECONDS,
) -> str:
    if digits < 6 or digits > 8:
        raise ValueError("nombre de chiffres TOTP invalide")
    if period < 15 or period > 120:
        raise ValueError("période TOTP invalide")
    counter = int(timestamp) // int(period)
    digest = hmac.new(
        _b32_decode(secret),
        struct.pack(">Q", counter),
        hashlib.sha1,
    ).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % (10 ** digits)).zfill(digits)


def matching_step(
    secret: str,
    code: str,
    *,
    now: int | float | None = None,
    window: int = TOTP_WINDOW,
) -> int | None:
    """Return the TOTP time-step matched by ``code`` or ``None``."""
    candidate = str(code or "").strip()
    if not _CODE_RE.fullmatch(candidate):
        return None
    instant = int(time.time() if now is None else now)
    for delta in range(-max(0, int(window)), max(0, int(window)) + 1):
        moment = instant + delta * TOTP_PERIOD_SECONDS
        expected = totp_at(secret, moment)
        if hmac.compare_digest(expected, candidate):
            return moment // TOTP_PERIOD_SECONDS
    return None


def verify_totp(
    secret: str,
    code: str,
    *,
    now: int | float | None = None,
    window: int = TOTP_WINDOW,
) -> bool:
    return matching_step(secret, code, now=now, window=window) is not None


def _last_step() -> int:
    path = _last_step_path()
    if path.is_symlink() or not path.is_file():
        return -1
    try:
        return int(path.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return -1


def _record_step(step: int) -> None:
    _atomic_write(_last_step_path(), f"{int(step)}\n".encode("ascii"))


def _read_secret() -> str:
    path = _secret_path()
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("2FA non configurée")
    secret = path.read_text(encoding="ascii").strip()
    _b32_decode(secret)
    return secret


def configured() -> bool:
    try:
        _read_secret()
        return True
    except Exception:
        return False


def _pending() -> dict:
    path = _pending_path()
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("enrôlement 2FA absent")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError("enrôlement 2FA invalide") from exc
    if payload.get("schemaVersion") != 1:
        raise RuntimeError("enrôlement 2FA invalide")
    secret = str(payload.get("secret") or "")
    _b32_decode(secret)
    created = payload.get("createdAt")
    if isinstance(created, bool):
        raise RuntimeError("enrôlement 2FA invalide")
    try:
        created_at = int(created)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("enrôlement 2FA invalide") from exc
    return {"secret": secret, "createdAt": created_at}


def provisioning_uri(
    secret: str,
    *,
    account: str = "admin",
    issuer: str = "CheckupAuto",
) -> str:
    _b32_decode(secret)
    safe_issuer = str(issuer or "CheckupAuto").strip()[:80] or "CheckupAuto"
    safe_account = str(account or "admin").strip()[:120] or "admin"
    label = quote(f"{safe_issuer}:{safe_account}", safe="")
    query = urlencode({
        "secret": secret,
        "issuer": safe_issuer,
        "algorithm": "SHA1",
        "digits": str(TOTP_DIGITS),
        "period": str(TOTP_PERIOD_SECONDS),
    })
    return f"otpauth://totp/{label}?{query}"


def begin_enrollment(
    *,
    account: str = "admin",
    issuer: str = "CheckupAuto",
    now: int | None = None,
) -> dict:
    if configured():
        raise RuntimeError("2FA déjà configurée")
    secret = generate_secret()
    created = int(time.time() if now is None else now)
    payload = {
        "schemaVersion": 1,
        "secret": secret,
        "createdAt": created,
    }
    _atomic_write(
        _pending_path(),
        (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8"),
    )
    return {
        "secret": secret,
        "otpauthUri": provisioning_uri(
            secret,
            account=account,
            issuer=issuer,
        ),
        "expiresAt": created + PENDING_TTL_SECONDS,
    }


def pending_qr_svg() -> bytes:
    pending = _pending()
    uri = provisioning_uri(pending["secret"])
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=4,
    )
    qr.add_data(uri)
    qr.make(fit=True)
    image = qr.make_image(image_factory=SvgPathImage)
    output = BytesIO()
    image.save(output)
    return output.getvalue()


def _normalize_recovery(code: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", str(code or "")).upper()


def _recovery_hash(code: str) -> str:
    normalized = _normalize_recovery(code)
    if not _RECOVERY_RE.fullmatch(normalized):
        raise ValueError("code de récupération invalide")
    return hashlib.sha256(
        ("checkupauto-recovery-v1|" + normalized).encode("ascii")
    ).hexdigest()


def _new_recovery_codes() -> list[str]:
    rows = []
    for _ in range(_RECOVERY_COUNT):
        raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(12))
        rows.append(raw[:4] + "-" + raw[4:8] + "-" + raw[8:12])
    return rows


def _write_recovery(codes: list[str]) -> None:
    payload = {
        "schemaVersion": 1,
        "hashes": [_recovery_hash(code) for code in codes],
    }
    _atomic_write(
        _recovery_path(),
        (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8"),
    )


def recovery_remaining() -> int:
    path = _recovery_path()
    if path.is_symlink() or not path.is_file():
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        hashes = payload.get("hashes")
    except Exception:
        return 0
    if payload.get("schemaVersion") != 1 or not isinstance(hashes, list):
        return 0
    return sum(
        1
        for value in hashes
        if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)
    )


def _consume_recovery(code: str) -> bool:
    path = _recovery_path()
    if path.is_symlink() or not path.is_file():
        return False
    try:
        candidate = _recovery_hash(code)
        payload = json.loads(path.read_text(encoding="utf-8"))
        hashes = list(payload.get("hashes") or [])
    except Exception:
        return False
    if payload.get("schemaVersion") != 1:
        return False
    match_index = None
    for index, value in enumerate(hashes):
        if isinstance(value, str) and hmac.compare_digest(value, candidate):
            match_index = index
            break
    if match_index is None:
        return False
    del hashes[match_index]
    _atomic_write(
        path,
        (json.dumps(
            {"schemaVersion": 1, "hashes": hashes},
            sort_keys=True,
        ) + "\n").encode("utf-8"),
    )
    return True


def _secret_version() -> str:
    return hashlib.sha256(_read_secret().encode("ascii")).hexdigest()[:16]


def _session_key(*, create: bool = True) -> bytes:
    path = _session_key_path()
    if path.exists():
        if path.is_symlink() or not path.is_file():
            raise RuntimeError("clé de session 2FA invalide")
        raw = path.read_bytes()
        if len(raw) != 32:
            raise RuntimeError("clé de session 2FA invalide")
        return raw
    if not create:
        raise RuntimeError("clé de session 2FA absente")
    raw = secrets.token_bytes(32)
    _atomic_write(path, raw)
    return raw


def _rotate_session_key() -> None:
    _atomic_write(_session_key_path(), secrets.token_bytes(32))


def invalidate_all_sessions() -> None:
    """Revoke every previously issued MFA cookie after credential rotation."""
    with _state_lock():
        _rotate_session_key()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    raw = str(value or "")
    padding = "=" * ((4 - len(raw) % 4) % 4)
    return base64.urlsafe_b64decode(raw + padding)


def issue_session(
    *,
    now: int | None = None,
    ttl: int = SESSION_TTL_SECONDS,
) -> str:
    if not configured():
        raise RuntimeError("2FA non configurée")
    issued = int(time.time() if now is None else now)
    duration = max(300, min(int(ttl), 24 * 3600))
    payload = {
        "v": 1,
        "u": "admin",
        "iat": issued,
        "exp": issued + duration,
        "mfa": _secret_version(),
        "n": secrets.token_urlsafe(12),
    }
    body = _b64url(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    signature = _b64url(
        hmac.new(
            _session_key(),
            body.encode("ascii"),
            hashlib.sha256,
        ).digest()
    )
    return body + "." + signature


def validate_session(token: str, *, now: int | None = None) -> bool:
    raw = str(token or "").strip()
    try:
        body, signature = raw.split(".", 1)
    except ValueError:
        return False
    try:
        expected = _b64url(
            hmac.new(
                _session_key(create=False),
                body.encode("ascii"),
                hashlib.sha256,
            ).digest()
        )
    except Exception:
        return False
    if not hmac.compare_digest(signature, expected):
        return False
    try:
        payload = json.loads(_b64url_decode(body).decode("utf-8"))
    except Exception:
        return False
    instant = int(time.time() if now is None else now)
    if payload.get("v") != 1 or payload.get("u") != "admin":
        return False
    if not isinstance(payload.get("iat"), int) or not isinstance(payload.get("exp"), int):
        return False
    if payload["iat"] > instant + 60 or payload["exp"] <= instant:
        return False
    if _is_revoked(payload.get("n")):
        return False
    try:
        return hmac.compare_digest(
            str(payload.get("mfa") or ""),
            _secret_version(),
        )
    except Exception:
        return False


def _session_payload(token: str) -> dict | None:
    raw = str(token or "").strip()
    try:
        body, signature = raw.split(".", 1)
        expected = _b64url(
            hmac.new(_session_key(create=False), body.encode("ascii"), hashlib.sha256).digest()
        )
    except Exception:
        return None
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        payload = json.loads(_b64url_decode(body).decode("utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _revoked() -> dict:
    path = _revoked_path()
    if path.is_symlink() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    entries = payload.get("revoked") if isinstance(payload, dict) else None
    if not isinstance(entries, dict):
        return {}
    return {str(k): int(v) for k, v in entries.items() if isinstance(v, int) and not isinstance(v, bool)}


def _is_revoked(nonce: object) -> bool:
    return bool(nonce) and str(nonce) in _revoked()


def revoke_session(token: str, *, now: int | None = None) -> bool:
    """Invalidate one MFA session server-side (logout)."""
    payload = _session_payload(token)
    if not payload or not payload.get("n") or not isinstance(payload.get("exp"), int):
        return False
    instant = int(time.time() if now is None else now)
    with _state_lock():
        entries = {k: v for k, v in _revoked().items() if v > instant}
        entries[str(payload["n"])] = int(payload["exp"])
        _atomic_write(
            _revoked_path(),
            (json.dumps({"schemaVersion": 1, "revoked": entries}, sort_keys=True) + "\n").encode("utf-8"),
        )
    return True


def token_from_cookie(cookie_header: str) -> str:
    cookie = SimpleCookie()
    try:
        cookie.load(str(cookie_header or ""))
    except Exception:
        return ""
    morsel = cookie.get(COOKIE_NAME)
    return morsel.value if morsel is not None else ""


def session_cookie(token: str, *, max_age: int = SESSION_TTL_SECONDS) -> str:
    if not token or any(ch in token for ch in "\r\n;"):
        raise ValueError("token de session 2FA invalide")
    return (
        f"{COOKIE_NAME}={token}; Path=/; Max-Age={int(max_age)}; "
        "HttpOnly; Secure; SameSite=Strict"
    )


def clear_session_cookie() -> str:
    return (
        f"{COOKIE_NAME}=; Path=/; Max-Age=0; "
        "HttpOnly; Secure; SameSite=Strict"
    )


def confirm_enrollment(
    code: str,
    *,
    now: int | None = None,
) -> dict:
    if configured():
        raise RuntimeError("2FA déjà configurée")
    pending = _pending()
    instant = int(time.time() if now is None else now)
    if instant - pending["createdAt"] > PENDING_TTL_SECONDS or instant < pending["createdAt"] - 60:
        try:
            _pending_path().unlink()
        except FileNotFoundError:
            pass
        raise RuntimeError("enrôlement 2FA expiré")
    step = matching_step(pending["secret"], code, now=instant)
    if step is None:
        raise PermissionError("code TOTP invalide")
    _record_step(step)

    recovery = _new_recovery_codes()
    _write_recovery(recovery)
    _rotate_session_key()
    _atomic_write(
        _secret_path(),
        (pending["secret"] + "\n").encode("ascii"),
    )
    try:
        _pending_path().unlink()
    except FileNotFoundError:
        pass

    token = issue_session(now=instant)
    return {
        "sessionToken": token,
        "recoveryCodes": recovery,
        "recoveryRemaining": len(recovery),
    }


def verify_login(
    code: str,
    *,
    now: int | None = None,
) -> dict:
    secret = _read_secret()
    instant = int(time.time() if now is None else now)
    candidate = str(code or "").strip()
    used_recovery = False
    with _state_lock():
        step = matching_step(secret, candidate, now=instant)
        if step is not None:
            # A TOTP code is single use: reject replay of the same or an older step.
            valid = step > _last_step()
            if valid:
                _record_step(step)
        else:
            valid = _consume_recovery(candidate)
            used_recovery = valid
    if not valid:
        raise PermissionError("second facteur invalide")
    return {
        "sessionToken": issue_session(now=instant),
        "usedRecoveryCode": used_recovery,
        "recoveryRemaining": recovery_remaining(),
    }


def status(cookie_header: str = "", *, now: int | None = None) -> dict:
    active = configured()
    token = token_from_cookie(cookie_header)
    return {
        "configured": active,
        "required": required(),
        "sessionAuthenticated": bool(active and validate_session(token, now=now)),
        "recoveryRemaining": recovery_remaining() if active else 0,
    }
