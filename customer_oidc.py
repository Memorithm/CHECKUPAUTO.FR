"""OIDC federation for CheckupAuto customer accounts.

Supports Google, Sign in with Apple and Microsoft consumer accounts. Every login
uses state, nonce and PKCE. ID tokens are signature-verified against pinned
provider JWKS endpoints before a CheckupAuto session may be issued.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

import customer_accounts
from sqlite_closing import ClosingConnection

PROVIDERS = {
    "google": {
        "label": "Google",
        "issuer": "https://accounts.google.com",
        "authorize": "https://accounts.google.com/o/oauth2/v2/auth",
        "token": "https://oauth2.googleapis.com/token",
        "jwks": "https://www.googleapis.com/oauth2/v3/certs",
        "scope": "openid email profile",
        "responseMode": "query",
    },
    "apple": {
        "label": "Apple",
        "issuer": "https://appleid.apple.com",
        "authorize": "https://appleid.apple.com/auth/authorize",
        "token": "https://appleid.apple.com/auth/token",
        "jwks": "https://appleid.apple.com/auth/keys",
        "scope": "openid email",
        "responseMode": "form_post",
    },
    "microsoft": {
        "label": "Microsoft / Hotmail",
        "issuer": "https://login.microsoftonline.com/9188040d-6c67-4c5b-b112-36a304b66dad/v2.0",
        "authorize": "https://login.microsoftonline.com/consumers/oauth2/v2.0/authorize",
        "token": "https://login.microsoftonline.com/consumers/oauth2/v2.0/token",
        "jwks": "https://login.microsoftonline.com/consumers/discovery/v2.0/keys",
        "scope": "openid email profile",
        "responseMode": "query",
    },
}
FLOW_TTL_MINUTES = 10
MAX_CONFIG_BYTES = 32768


class CustomerOIDCError(ValueError):
    pass


def _config_path() -> Path:
    override = str(os.environ.get("CYBERCHECK_CUSTOMER_OIDC_CONFIG_PATH") or "").strip()
    if override:
        return Path(override)
    return Path(os.environ.get("CYBERCHECK_PRIVATE_DIR", "/root/CyberCheckPrivate")) / "customer" / "oidc.json"


def _flow_path() -> Path:
    return Path(os.environ.get("CYBERCHECK_DATA_DIR", "/root/CyberCheckData")) / "customer-oidc.sqlite3"


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _provider(value: object) -> str:
    raw = str(value or "").strip().lower()
    if raw not in PROVIDERS:
        raise CustomerOIDCError("customer_oidc_provider_invalid")
    return raw


def _origin(value: object) -> str:
    raw = str(value or "").strip().rstrip("/")
    if not re.fullmatch(r"https://[A-Za-z0-9.-]+(?::[0-9]{1,5})?", raw):
        raise CustomerOIDCError("customer_oidc_origin_invalid")
    return raw


def _load_config() -> dict:
    path = _config_path()
    if not path.is_file() or path.is_symlink():
        return {"providers": {}}
    if path.stat().st_size > MAX_CONFIG_BYTES or path.stat().st_mode & 0o077:
        raise CustomerOIDCError("customer_oidc_config_invalid")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        raise CustomerOIDCError("customer_oidc_config_invalid") from None
    if not isinstance(doc, dict) or set(doc) != {"providers"} or not isinstance(doc["providers"], dict):
        raise CustomerOIDCError("customer_oidc_config_invalid")
    return doc


def provider_status() -> list[dict]:
    try:
        cfg = _load_config()["providers"]
    except CustomerOIDCError:
        cfg = {}
    result = []
    for key, meta in PROVIDERS.items():
        item = cfg.get(key)
        configured = (
            isinstance(item, dict)
            and isinstance(item.get("clientId"), str)
            and 1 <= len(item["clientId"].strip()) <= 512
            and isinstance(item.get("clientSecret"), str)
            and 1 <= len(item["clientSecret"]) <= 4096
        )
        result.append({
            "id": key,
            "label": meta["label"],
            "configured": bool(configured),
        })
    return result


def _provider_config(provider: str) -> dict:
    provider = _provider(provider)
    item = _load_config()["providers"].get(provider)
    if not isinstance(item, dict):
        raise CustomerOIDCError("customer_oidc_not_configured")
    client_id = str(item.get("clientId") or "").strip()
    client_secret = str(item.get("clientSecret") or "")
    if not client_id or len(client_id) > 512 or not client_secret or len(client_secret) > 4096:
        raise CustomerOIDCError("customer_oidc_not_configured")
    return {"clientId": client_id, "clientSecret": client_secret}


def _connect() -> sqlite3.Connection:
    path = _flow_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10, factory=ClosingConnection)
    db.row_factory = sqlite3.Row
    return db


def init_db() -> None:
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            """CREATE TABLE IF NOT EXISTS customer_oidc_flow(
              state_hash TEXT PRIMARY KEY,
              provider TEXT NOT NULL,
              nonce TEXT NOT NULL,
              verifier TEXT NOT NULL,
              redirect_uri TEXT NOT NULL,
              created_at TEXT NOT NULL,
              expires_at TEXT NOT NULL,
              browser_hash TEXT NOT NULL DEFAULT '',
              mobile INTEGER NOT NULL DEFAULT 0,
              return_to TEXT NOT NULL DEFAULT '',
              mobile_challenge TEXT NOT NULL DEFAULT ''
            )"""
        )
        columns = {row[1] for row in db.execute("PRAGMA table_info(customer_oidc_flow)")}
        if "browser_hash" not in columns:
            db.execute("ALTER TABLE customer_oidc_flow ADD COLUMN browser_hash TEXT NOT NULL DEFAULT ''")
        if "mobile" not in columns:
            db.execute("ALTER TABLE customer_oidc_flow ADD COLUMN mobile INTEGER NOT NULL DEFAULT 0")
        if "return_to" not in columns:
            db.execute("ALTER TABLE customer_oidc_flow ADD COLUMN return_to TEXT NOT NULL DEFAULT ''")
        if "mobile_challenge" not in columns:
            db.execute("ALTER TABLE customer_oidc_flow ADD COLUMN mobile_challenge TEXT NOT NULL DEFAULT ''")
        db.execute("CREATE INDEX IF NOT EXISTS idx_customer_oidc_expiry ON customer_oidc_flow(expires_at)")
        db.execute(
            """CREATE TABLE IF NOT EXISTS customer_native_nonce(
              nonce_hash TEXT PRIMARY KEY,
              server_issued INTEGER NOT NULL DEFAULT 0,
              used_at TEXT NOT NULL DEFAULT '',
              expires_at TEXT NOT NULL
            )"""
        )
    try:
        _flow_path().chmod(0o600)
    except PermissionError:
        pass


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _browser_hash(binding: object) -> str:
    if not isinstance(binding, str) or not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", binding):
        raise CustomerOIDCError("customer_oidc_browser_invalid")
    return hashlib.sha256(binding.encode("ascii")).hexdigest()


def _return_to(value: object) -> str:
    raw=str(value or "").strip()
    if not raw:
        return ""
    if len(raw)>2048 or any(ord(ch)<32 for ch in raw):
        raise CustomerOIDCError("customer_oidc_return_invalid")
    parts=urlsplit(raw)
    if parts.scheme or parts.netloc or parts.fragment or not parts.path.startswith("/") or raw.startswith("//"):
        raise CustomerOIDCError("customer_oidc_return_invalid")
    return parts.path+(("?" + parts.query) if parts.query else "")


def begin(provider: object, origin: object, *, browser_binding: str, mobile: bool=False, return_to: object="", mobile_challenge: object="") -> str:
    provider = _provider(provider)
    mobile_challenge = str(mobile_challenge or "").strip() if mobile else ""
    if mobile_challenge and not re.fullmatch(r"[A-Za-z0-9_-]{43}", mobile_challenge):
        raise CustomerOIDCError("customer_oidc_mobile_challenge_invalid")
    origin = _origin(origin)
    browser_hash = _browser_hash(browser_binding)
    return_to = _return_to(return_to)
    cfg = _provider_config(provider)
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48)
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    redirect_uri = f"{origin}/auth/customer/{provider}/callback"
    now = _now()
    expires = now + dt.timedelta(minutes=FLOW_TTL_MINUTES)
    init_db()
    with _connect() as db:
        db.execute("DELETE FROM customer_oidc_flow WHERE expires_at<?", (now.isoformat(timespec="seconds"),))
        db.execute(
            """INSERT INTO customer_oidc_flow(
                 state_hash,provider,nonce,verifier,redirect_uri,created_at,expires_at,browser_hash,mobile,return_to,mobile_challenge
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                hashlib.sha256(state.encode()).hexdigest(),
                provider,
                nonce,
                verifier,
                redirect_uri,
                now.isoformat(timespec="seconds"),
                expires.isoformat(timespec="seconds"),
                browser_hash,
                1 if mobile else 0,
                return_to,
                mobile_challenge,
            ),
        )
    meta = PROVIDERS[provider]
    params = {
        "client_id": cfg["clientId"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": meta["scope"],
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "response_mode": meta["responseMode"],
    }
    return meta["authorize"] + "?" + urlencode(params)


def _consume_flow(provider: str, state: object, *, browser_binding: str, origin: str) -> dict:
    browser_hash = _browser_hash(browser_binding)
    redirect_uri = f"{_origin(origin)}/auth/customer/{provider}/callback"
    state = str(state or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", state):
        raise CustomerOIDCError("customer_oidc_state_invalid")
    state_hash = hashlib.sha256(state.encode()).hexdigest()
    now = _now()
    init_db()
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT * FROM customer_oidc_flow WHERE state_hash=? AND provider=?",
            (state_hash, provider),
        ).fetchone()
        if not row:
            raise CustomerOIDCError("customer_oidc_state_invalid")
        if not hmac.compare_digest(row["browser_hash"], browser_hash) or not hmac.compare_digest(row["redirect_uri"], redirect_uri):
            raise CustomerOIDCError("customer_oidc_browser_invalid")
        db.execute("DELETE FROM customer_oidc_flow WHERE state_hash=?", (state_hash,))
    expires = dt.datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00"))
    if now >= expires:
        raise CustomerOIDCError("customer_oidc_state_expired")
    return dict(row)


def _decode_part(raw: str) -> dict:
    if not raw or len(raw) > 32768:
        raise CustomerOIDCError("customer_oidc_token_invalid")
    raw += "=" * (-len(raw) % 4)
    try:
        value = json.loads(base64.urlsafe_b64decode(raw.encode("ascii")))
    except Exception:
        raise CustomerOIDCError("customer_oidc_token_invalid") from None
    if not isinstance(value, dict):
        raise CustomerOIDCError("customer_oidc_token_invalid")
    return value


def _issuer_valid(provider: str, issuer: object) -> bool:
    if not isinstance(issuer, str):
        return False
    if provider == "google":
        return issuer in {"https://accounts.google.com", "accounts.google.com"}
    return issuer == PROVIDERS[provider]["issuer"]


def _jwk_key(jwk: dict):
    if jwk.get("kty") != "RSA":
        raise CustomerOIDCError("customer_oidc_token_invalid")
    try:
        n = int.from_bytes(base64.urlsafe_b64decode(str(jwk["n"]) + "=" * (-len(str(jwk["n"])) % 4)), "big")
        e = int.from_bytes(base64.urlsafe_b64decode(str(jwk["e"]) + "=" * (-len(str(jwk["e"])) % 4)), "big")
        return rsa.RSAPublicNumbers(e, n).public_key()
    except Exception:
        raise CustomerOIDCError("customer_oidc_token_invalid") from None


def _verify_id_token(provider: str, raw: object, *, client_id: str, nonce: str, fetcher=None) -> dict:
    token = str(raw or "")
    parts = token.split(".")
    if len(parts) != 3:
        raise CustomerOIDCError("customer_oidc_token_invalid")
    header = _decode_part(parts[0])
    claims = _decode_part(parts[1])
    if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
        raise CustomerOIDCError("customer_oidc_token_invalid")
    fetch = fetcher or httpx.get
    try:
        response = fetch(PROVIDERS[provider]["jwks"], timeout=10)
        if int(response.status_code) != 200:
            raise CustomerOIDCError("customer_oidc_jwks_unavailable")
        jwks = response.json()
    except CustomerOIDCError:
        raise
    except Exception:
        raise CustomerOIDCError("customer_oidc_jwks_unavailable") from None
    keys = jwks.get("keys") if isinstance(jwks, dict) else None
    candidates = [jwk for jwk in (keys or []) if isinstance(jwk, dict) and jwk.get("kid") == header["kid"]]
    if len(candidates) != 1:
        raise CustomerOIDCError("customer_oidc_token_invalid")
    signature_raw = parts[2] + "=" * (-len(parts[2]) % 4)
    try:
        signature = base64.urlsafe_b64decode(signature_raw.encode("ascii"))
        _jwk_key(candidates[0]).verify(
            signature,
            (parts[0] + "." + parts[1]).encode("ascii"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except CustomerOIDCError:
        raise
    except Exception:
        raise CustomerOIDCError("customer_oidc_token_invalid") from None

    now = int(_now().timestamp())
    aud = claims.get("aud")
    audience_ok = (
        isinstance(aud, str) and aud == client_id
        or isinstance(aud, list) and bool(aud) and all(isinstance(a, str) for a in aud) and client_id in aud
    )
    azp = claims.get("azp")
    authorized_party_ok = (
        (azp is None or azp == client_id)
        and (not isinstance(aud, list) or len(aud) <= 1 or azp == client_id)
    )
    issued_at = claims.get("iat")
    not_before = claims.get("nbf", now)
    if (
        not _issuer_valid(provider, claims.get("iss"))
        or not audience_ok
        or not authorized_party_ok
        or type(claims.get("exp")) is not int
        or claims["exp"] <= now
        or type(issued_at) is not int or issued_at > now + 60
        or type(not_before) is not int or not_before > now + 60
        or not isinstance(claims.get("nonce"), str) or claims["nonce"] != nonce
        or not isinstance(claims.get("sub"), str) or not 1 <= len(claims["sub"]) <= 512
    ):
        raise CustomerOIDCError("customer_oidc_token_invalid")
    return claims


def verify_native_apple_identity(id_token: object, *, client_id: object, nonce: object = "", jwks_fetcher=None) -> dict:
    """Verify a native Sign in with Apple identity token.

    The native iOS App ID is a distinct audience from the web Services ID.
    This helper deliberately performs verification only; HTTP/session policy
    remains outside the cryptographic primitive.
    """
    audience = str(client_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9.-]{3,255}", audience):
        raise CustomerOIDCError("customer_oidc_client_id_invalid")
    token = str(id_token or "").strip()
    parts = token.split(".")
    if len(parts) != 3:
        raise CustomerOIDCError("customer_oidc_token_invalid")
    claims_preview = _decode_part(parts[1])
    token_nonce = claims_preview.get("nonce")
    expected_nonce = str(nonce or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", expected_nonce):
        raise CustomerOIDCError("customer_oidc_nonce_invalid")
    expected_token_nonce = hashlib.sha256(expected_nonce.encode("ascii")).hexdigest()
    return _verify_id_token(
        "apple",
        token,
        client_id=audience,
        nonce=expected_token_nonce,
        fetcher=jwks_fetcher,
    )


def complete(provider: object, state: object, code: object, *, browser_binding: str, origin: str, poster=None, jwks_fetcher=None) -> dict:
    provider = _provider(provider)
    code = str(code or "").strip()
    if not code or len(code) > 4096:
        raise CustomerOIDCError("customer_oidc_code_invalid")
    flow = _consume_flow(provider, state, browser_binding=browser_binding, origin=origin)
    cfg = _provider_config(provider)
    post = poster or httpx.post
    try:
        response = post(
            PROVIDERS[provider]["token"],
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": cfg["clientId"],
                "client_secret": cfg["clientSecret"],
                "redirect_uri": flow["redirect_uri"],
                "code_verifier": flow["verifier"],
            },
            headers={"Accept": "application/json"},
            timeout=12,
        )
        if int(response.status_code) != 200:
            raise CustomerOIDCError("customer_oidc_exchange_failed")
        payload = response.json()
    except CustomerOIDCError:
        raise
    except Exception:
        raise CustomerOIDCError("customer_oidc_exchange_failed") from None
    if not isinstance(payload, dict) or not isinstance(payload.get("id_token"), str):
        raise CustomerOIDCError("customer_oidc_exchange_failed")
    claims = _verify_id_token(
        provider,
        payload["id_token"],
        client_id=cfg["clientId"],
        nonce=str(flow["nonce"]),
        fetcher=jwks_fetcher,
    )
    subject = str(claims.get("sub") or "")
    # Only the signed ``email`` claim is used: ``preferred_username`` is not a
    # verified address (audit S-08).  Microsoft does not assert
    # ``email_verified``, so that latent provider fails closed until a
    # verified-domain policy exists.
    email = str(claims.get("email") or "")
    if provider == "microsoft" and claims.get("email_verified") is not True:
        raise CustomerOIDCError("customer_oidc_email_unverified")
    if provider == "google" and claims.get("email_verified") is not True:
        raise CustomerOIDCError("customer_oidc_email_unverified")
    if provider == "apple" and str(claims.get("email_verified") or "").lower() not in {"true", "1"}:
        raise CustomerOIDCError("customer_oidc_email_unverified")
    if not email:
        raise CustomerOIDCError("customer_oidc_email_missing")
    name = str(claims.get("name") or "").strip()
    if not name:
        name = email.split("@", 1)[0][:120] or "Client Checkup Auto"
    account = customer_accounts.create_from_verified_identity(
        provider,
        subject,
        email,
        name,
        email_verified=True,
    )
    session = customer_accounts.issue_session(account["accountId"])
    return {
        "account": account,
        "session": session,
        "mobile": bool(flow.get("mobile",0)),
        "returnTo": str(flow.get("return_to") or ""),
        "mobileChallenge": str(flow.get("mobile_challenge") or ""),
    }


def purge_expired_flows(*, dry_run: bool = False) -> int:
    """Remove abandoned OIDC login flows once they can no longer complete."""
    if not _flow_path().is_file():
        return 0
    init_db()
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    from contextlib import closing
    with closing(_connect()) as db:
        count = int(db.execute("SELECT COUNT(*) FROM customer_oidc_flow WHERE expires_at<?", (now,)).fetchone()[0])
        count += int(db.execute("SELECT COUNT(*) FROM customer_native_nonce WHERE expires_at<?", (now,)).fetchone()[0])
        if count and not dry_run:
            db.execute("DELETE FROM customer_oidc_flow WHERE expires_at<?", (now,))
            db.execute("DELETE FROM customer_native_nonce WHERE expires_at<?", (now,))
            db.commit()
    return count


# --- Native Sign in with Apple nonces (audit S-06) -------------------------
NATIVE_NONCE_TTL_MINUTES = 10
# Identity tokens are short-lived; a consumed nonce is remembered well beyond
# their lifetime so a stolen token+nonce pair cannot be replayed.
NATIVE_NONCE_REPLAY_HOURS = 24
NATIVE_NONCE_REQUIRED_ENV = "CYBERCHECK_APPLE_SERVER_NONCE_REQUIRED"


def native_nonce_required() -> bool:
    return os.environ.get(NATIVE_NONCE_REQUIRED_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def issue_native_nonce() -> dict:
    """Issue a single-use, short-lived nonce for the native Apple flow."""
    nonce = secrets.token_urlsafe(32)
    now = _now()
    expires = now + dt.timedelta(minutes=NATIVE_NONCE_TTL_MINUTES)
    init_db()
    from contextlib import closing
    with closing(_connect()) as db, db:
        db.execute(
            "INSERT INTO customer_native_nonce(nonce_hash,server_issued,used_at,expires_at) VALUES(?,?,?,?)",
            (hashlib.sha256(nonce.encode("ascii")).hexdigest(), 1, "", expires.isoformat(timespec="seconds")),
        )
    return {"nonce": nonce, "expiresAt": expires.isoformat(timespec="seconds")}


def consume_native_nonce(nonce: object) -> None:
    """Burn a native nonce after its identity token was verified.

    A nonce issued by the server must be unexpired and unused.  A nonce chosen
    by the app (legacy builds) is accepted once unless the server-issued mode
    is required, so a replay of the same token and nonce is always refused.
    """
    raw = str(nonce or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", raw):
        raise CustomerOIDCError("customer_oidc_nonce_invalid")
    digest = hashlib.sha256(raw.encode("ascii")).hexdigest()
    now = _now()
    init_db()
    from contextlib import closing
    with closing(_connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT server_issued,used_at,expires_at FROM customer_native_nonce WHERE nonce_hash=?",
            (digest,),
        ).fetchone()
        replay_until = (now + dt.timedelta(hours=NATIVE_NONCE_REPLAY_HOURS)).isoformat(timespec="seconds")
        if row is None:
            if native_nonce_required():
                raise CustomerOIDCError("customer_oidc_nonce_unknown")
            db.execute(
                "INSERT INTO customer_native_nonce(nonce_hash,server_issued,used_at,expires_at) VALUES(?,?,?,?)",
                (digest, 0, now.isoformat(timespec="seconds"), replay_until),
            )
            return
        if str(row["used_at"] or ""):
            raise CustomerOIDCError("customer_oidc_nonce_replayed")
        expires = dt.datetime.fromisoformat(str(row["expires_at"]))
        if now >= expires:
            raise CustomerOIDCError("customer_oidc_nonce_expired")
        db.execute(
            "UPDATE customer_native_nonce SET used_at=?,expires_at=? WHERE nonce_hash=?",
            (now.isoformat(timespec="seconds"), replay_until, digest),
        )
