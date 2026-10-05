"""Customer account core for the CheckupAuto web dashboard.

Verified external identities are mapped to an internal UUID. Profile PII is
encrypted at rest; lookup keys are HMACs. Sessions are opaque, hashed server-side
and never shared with the mobile installation authentication model.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import uuid
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import referral_engine

PROVIDERS = {"google", "apple", "microsoft"}
ACCOUNT_KINDS = {"individual", "professional"}
SESSION_TTL_HOURS = 12
PASSAGE_CONFIRMATION_TTL_MINUTES = 30
AAD_PREFIX = b"checkupauto-customer-profile-v1\x00"


class CustomerAccountError(ValueError):
    pass


def data_path() -> Path:
    return Path(os.environ.get("CYBERCHECK_DATA_DIR", "/root/CyberCheckData")) / "customer-accounts.sqlite3"


def _key_path() -> Path:
    return Path(os.environ.get("CYBERCHECK_PRIVATE_DIR", "/root/CyberCheckPrivate")) / "customer" / "accounts.key"


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _now_iso() -> str:
    return _now().isoformat(timespec="seconds")


def _ensure_key() -> bytes:
    path = _key_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except PermissionError:
        pass
    if path.is_symlink():
        raise RuntimeError("customer_account_key_invalid")
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(secrets.token_bytes(32))
            handle.flush()
            os.fsync(handle.fileno())
    try:
        path.chmod(0o600)
    except PermissionError:
        pass
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as handle:
        key = handle.read(33)
    if len(key) != 32:
        raise RuntimeError("customer_account_key_invalid")
    return key


def _hmac(label: str, value: str) -> str:
    return hmac.new(_ensure_key(), (label + "\x00" + value).encode("utf-8"), hashlib.sha256).hexdigest()


def _provider(value: object) -> str:
    raw = str(value or "").strip().lower()
    if raw not in PROVIDERS:
        raise CustomerAccountError("customer_provider_invalid")
    return raw


def _subject(value: object) -> str:
    raw = str(value or "").strip()
    if not raw or len(raw) > 512 or "\x00" in raw:
        raise CustomerAccountError("customer_subject_invalid")
    return raw


def _email(value: object) -> str:
    raw = str(value or "").strip().lower()
    if len(raw) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", raw):
        raise CustomerAccountError("customer_email_invalid")
    return raw


def _phone(value: object) -> str:
    raw=" ".join(str(value or "").strip().split())
    if raw and (len(raw)>32 or not re.fullmatch(r"[+0-9(). /-]{6,32}",raw)):
        raise CustomerAccountError("customer_phone_invalid")
    return raw


def _address_line(value: object, *, optional: bool = False) -> str:
    raw=" ".join(str(value or "").strip().split())
    if not raw:
        return "" if optional else ""
    if len(raw)>180 or any(ord(ch)<32 for ch in raw):
        raise CustomerAccountError("customer_address_invalid")
    return raw


def _postal_code(value: object) -> str:
    raw=" ".join(str(value or "").strip().upper().split())
    if raw and (len(raw)>16 or not re.fullmatch(r"[0-9A-Z][0-9A-Z -]{1,15}",raw)):
        raise CustomerAccountError("customer_postal_code_invalid")
    return raw


def _city(value: object) -> str:
    raw=" ".join(str(value or "").strip().split())
    if raw and (len(raw)>120 or any(ord(ch)<32 for ch in raw)):
        raise CustomerAccountError("customer_city_invalid")
    return raw


def _display_name(value: object) -> str:
    raw = " ".join(str(value or "").strip().split())
    if not 1 <= len(raw) <= 120 or any(ord(ch) < 32 for ch in raw):
        raise CustomerAccountError("customer_display_name_invalid")
    return raw


def _kind(value: object) -> str:
    raw = str(value or "").strip().lower()
    if raw not in ACCOUNT_KINDS:
        raise CustomerAccountError("customer_kind_invalid")
    return raw


def _company_name(value: object, kind: str) -> str:
    raw = " ".join(str(value or "").strip().split())
    if kind == "professional":
        if not 2 <= len(raw) <= 160:
            raise CustomerAccountError("customer_company_name_invalid")
    elif raw:
        raise CustomerAccountError("customer_company_name_not_allowed")
    return raw


def _siret(value: object, kind: str) -> str:
    raw = re.sub(r"\s+", "", str(value or ""))
    if raw:
        if kind != "professional" or not re.fullmatch(r"[0-9]{14}", raw):
            raise CustomerAccountError("customer_siret_invalid")
    return raw


def _account_id(value: object) -> str:
    raw = str(value or "").strip().lower()
    try:
        parsed = uuid.UUID(raw)
    except (ValueError, AttributeError) as exc:
        raise CustomerAccountError("customer_account_id_invalid") from exc
    if str(parsed) != raw:
        raise CustomerAccountError("customer_account_id_invalid")
    return raw


def _connect() -> sqlite3.Connection:
    path = data_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except PermissionError:
        pass
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


def init_db() -> None:
    with _connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS customer_account(
              account_id TEXT PRIMARY KEY,
              kind TEXT NOT NULL CHECK(kind IN ('individual','professional')),
              email_hash TEXT NOT NULL UNIQUE,
              profile_blob BLOB NOT NULL,
              wallet_code TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS customer_identity(
              provider TEXT NOT NULL CHECK(provider IN ('google','apple','microsoft')),
              subject_hash TEXT NOT NULL,
              account_id TEXT NOT NULL REFERENCES customer_account(account_id) ON DELETE CASCADE,
              created_at TEXT NOT NULL,
              last_login_at TEXT NOT NULL,
              PRIMARY KEY(provider,subject_hash)
            );
            CREATE INDEX IF NOT EXISTS idx_customer_identity_account
              ON customer_identity(account_id,provider);
            CREATE TABLE IF NOT EXISTS customer_session(
              session_hash TEXT PRIMARY KEY,
              account_id TEXT NOT NULL REFERENCES customer_account(account_id) ON DELETE CASCADE,
              created_at TEXT NOT NULL,
              expires_at TEXT NOT NULL,
              last_seen_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_customer_session_account
              ON customer_session(account_id,expires_at);
            CREATE TABLE IF NOT EXISTS customer_passage_confirmation(
              passage_hash TEXT PRIMARY KEY,
              account_id TEXT NOT NULL REFERENCES customer_account(account_id) ON DELETE CASCADE,
              state TEXT NOT NULL CHECK(state IN ('pending','confirmed')),
              action TEXT NOT NULL DEFAULT '' CHECK(action IN ('','validated','modified')),
              contact_hash TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL,
              expires_at TEXT NOT NULL,
              confirmed_at TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_customer_passage_account
              ON customer_passage_confirmation(account_id,state,expires_at);
            """
        )
    try:
        data_path().chmod(0o600)
    except PermissionError:
        pass


def _encrypt_profile(account_id: str, profile: dict) -> bytes:
    raw = json.dumps(profile, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(raw) > 8192:
        raise CustomerAccountError("customer_profile_too_large")
    nonce = secrets.token_bytes(12)
    return nonce + AESGCM(_ensure_key()).encrypt(nonce, raw, AAD_PREFIX + account_id.encode("ascii"))


def _decrypt_profile(account_id: str, raw: bytes) -> dict:
    try:
        clear = AESGCM(_ensure_key()).decrypt(
            bytes(raw[:12]),
            bytes(raw[12:]),
            AAD_PREFIX + account_id.encode("ascii"),
        )
        profile = json.loads(clear.decode("utf-8"))
    except Exception:
        raise RuntimeError("customer_profile_unreadable") from None
    if not isinstance(profile, dict):
        raise RuntimeError("customer_profile_unreadable")
    return profile


def create_from_verified_identity(
    provider: object,
    subject: object,
    email: object,
    display_name: object,
    *,
    email_verified: bool,
) -> dict:
    """Create/login one account from a provider-verified identity.

    An e-mail collision with a different identity is not auto-linked. Linking
    identities is a separate authenticated operation to avoid account takeover.
    """
    if email_verified is not True:
        raise CustomerAccountError("customer_email_not_verified")
    provider = _provider(provider)
    subject = _subject(subject)
    email = _email(email)
    display_name = _display_name(display_name)
    subject_hash = _hmac("oidc:" + provider, subject)
    email_hash = _hmac("email", email)
    init_db()
    now = _now_iso()

    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        identity = db.execute(
            "SELECT account_id FROM customer_identity WHERE provider=? AND subject_hash=?",
            (provider, subject_hash),
        ).fetchone()
        if identity:
            account_id = str(identity["account_id"])
            db.execute(
                "UPDATE customer_identity SET last_login_at=? WHERE provider=? AND subject_hash=?",
                (now, provider, subject_hash),
            )
            return profile(account_id)

        collision = db.execute(
            "SELECT account_id FROM customer_account WHERE email_hash=?",
            (email_hash,),
        ).fetchone()
        if collision:
            raise CustomerAccountError("customer_account_link_required")

        account_id = str(uuid.uuid4())
        encrypted = _encrypt_profile(account_id, {
            "email": email,
            "displayName": display_name,
            "companyName": "",
            "siret": "",
            "phone": "",
            "addressLine1": "",
            "addressLine2": "",
            "postalCode": "",
            "city": "",
        })
        db.execute(
            """INSERT INTO customer_account(
                 account_id,kind,email_hash,profile_blob,wallet_code,created_at,updated_at
               ) VALUES(?,'individual',?,?, '',?,?)""",
            (account_id, email_hash, encrypted, now, now),
        )
        db.execute(
            """INSERT INTO customer_identity(
                 provider,subject_hash,account_id,created_at,last_login_at
               ) VALUES(?,?,?,?,?)""",
            (provider, subject_hash, account_id, now, now),
        )

    _ensure_wallet(account_id)
    return profile(account_id)


def _ensure_wallet(account_id: str) -> str:
    account_id = _account_id(account_id)
    init_db()
    with _connect() as db:
        row = db.execute(
            "SELECT wallet_code FROM customer_account WHERE account_id=?",
            (account_id,),
        ).fetchone()
        if not row:
            raise CustomerAccountError("customer_account_not_found")
        code = str(row["wallet_code"] or "")
        if code:
            return code
    wallet = referral_engine.create_account()
    code = str(wallet["code"])
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            "UPDATE customer_account SET wallet_code=?,updated_at=? WHERE account_id=? AND wallet_code=''",
            (code, _now_iso(), account_id),
        )
        row = db.execute(
            "SELECT wallet_code FROM customer_account WHERE account_id=?",
            (account_id,),
        ).fetchone()
        return str(row["wallet_code"])


def update_profile(
    account_id: object,
    *,
    kind: object,
    display_name: object,
    company_name: object = "",
    siret: object = "",
    phone: object = "",
    address_line1: object = "",
    address_line2: object = "",
    postal_code: object = "",
    city: object = "",
) -> dict:
    account_id = _account_id(account_id)
    kind = _kind(kind)
    display_name = _display_name(display_name)
    company_name = _company_name(company_name, kind)
    siret = _siret(siret, kind)
    phone = _phone(phone)
    address_line1 = _address_line(address_line1)
    address_line2 = _address_line(address_line2, optional=True)
    postal_code = _postal_code(postal_code)
    city = _city(city)
    init_db()
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT profile_blob FROM customer_account WHERE account_id=?",
            (account_id,),
        ).fetchone()
        if not row:
            raise CustomerAccountError("customer_account_not_found")
        current = _decrypt_profile(account_id, row["profile_blob"])
        current.update({
            "displayName": display_name,
            "companyName": company_name,
            "siret": siret,
            "phone": phone,
            "addressLine1": address_line1,
            "addressLine2": address_line2,
            "postalCode": postal_code,
            "city": city,
        })
        db.execute(
            "UPDATE customer_account SET kind=?,profile_blob=?,updated_at=? WHERE account_id=?",
            (kind, _encrypt_profile(account_id, current), _now_iso(), account_id),
        )
    return profile(account_id)


def update_contact_details(
    account_id: object,
    *,
    phone: object,
    address_line1: object,
    address_line2: object = "",
    postal_code: object,
    city: object,
) -> dict:
    account_id=_account_id(account_id)
    phone=_phone(phone)
    address_line1=_address_line(address_line1)
    address_line2=_address_line(address_line2,optional=True)
    postal_code=_postal_code(postal_code)
    city=_city(city)
    init_db()
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row=db.execute(
            "SELECT profile_blob FROM customer_account WHERE account_id=?",
            (account_id,),
        ).fetchone()
        if not row:
            raise CustomerAccountError("customer_account_not_found")
        current=_decrypt_profile(account_id,row["profile_blob"])
        current.update({
            "phone":phone,
            "addressLine1":address_line1,
            "addressLine2":address_line2,
            "postalCode":postal_code,
            "city":city,
        })
        db.execute(
            "UPDATE customer_account SET profile_blob=?,updated_at=? WHERE account_id=?",
            (_encrypt_profile(account_id,current),_now_iso(),account_id),
        )
    return profile(account_id)


def _contact_details(profile_data: dict) -> dict:
    return {
        "email":str(profile_data.get("email") or ""),
        "phone":str(profile_data.get("phone") or ""),
        "addressLine1":str(profile_data.get("addressLine1") or ""),
        "addressLine2":str(profile_data.get("addressLine2") or ""),
        "postalCode":str(profile_data.get("postalCode") or ""),
        "city":str(profile_data.get("city") or ""),
    }


def _contact_complete(profile_data: dict) -> bool:
    contact=_contact_details(profile_data)
    return bool(
        contact["email"]
        and contact["phone"]
        and contact["addressLine1"]
        and contact["postalCode"]
        and contact["city"]
    )


def _contact_hash(account_id: str, profile_data: dict) -> str:
    canonical=json.dumps(
        _contact_details(profile_data),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",",":"),
    )
    return _hmac("contact-confirmation:"+account_id,canonical)


def begin_passage_confirmation(account_id: object) -> dict:
    account_id=_account_id(account_id)
    current=profile(account_id)
    token=secrets.token_urlsafe(32)
    passage_hash=hashlib.sha256(token.encode("ascii")).hexdigest()
    now=_now()
    expires=now+dt.timedelta(minutes=PASSAGE_CONFIRMATION_TTL_MINUTES)
    init_db()
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            "DELETE FROM customer_passage_confirmation WHERE expires_at<?",
            (now.isoformat(timespec="seconds"),),
        )
        db.execute(
            """INSERT INTO customer_passage_confirmation(
                 passage_hash,account_id,state,created_at,expires_at
               ) VALUES(?,?,'pending',?,?)""",
            (
                passage_hash,
                account_id,
                now.isoformat(timespec="seconds"),
                expires.isoformat(timespec="seconds"),
            ),
        )
    return {
        "passageToken":token,
        "expiresAt":expires.isoformat(timespec="seconds"),
        "contactDetailsComplete":bool(current.get("contactDetailsComplete")),
    }


def _passage_row(account_id: str, passage_token: object):
    raw=str(passage_token or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}",raw):
        raise PermissionError("customer_passage_invalid")
    digest=hashlib.sha256(raw.encode("ascii")).hexdigest()
    init_db()
    with _connect() as db:
        row=db.execute(
            """SELECT passage_hash,account_id,state,action,contact_hash,
                      created_at,expires_at,confirmed_at
               FROM customer_passage_confirmation
               WHERE passage_hash=? AND account_id=?""",
            (digest,account_id),
        ).fetchone()
    if not row:
        raise PermissionError("customer_passage_invalid")
    expires=dt.datetime.fromisoformat(str(row["expires_at"]).replace("Z","+00:00"))
    if _now()>=expires:
        raise PermissionError("customer_passage_expired")
    return row


def confirm_passage_contact(
    account_id: object,
    passage_token: object,
    *,
    action: object,
) -> dict:
    account_id=_account_id(account_id)
    action=str(action or "").strip().lower()
    if action not in {"validated","modified"}:
        raise CustomerAccountError("customer_passage_action_invalid")
    row=_passage_row(account_id,passage_token)
    if str(row["state"])!="pending":
        raise RuntimeError("customer_passage_not_pending")
    current=profile(account_id)
    if not bool(current.get("contactDetailsComplete")):
        raise CustomerAccountError("customer_contact_details_incomplete")
    contact_hash=_contact_hash(account_id,current)
    stamp=_now_iso()
    digest=str(row["passage_hash"])
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        updated=db.execute(
            """UPDATE customer_passage_confirmation
               SET state='confirmed',action=?,contact_hash=?,confirmed_at=?
               WHERE passage_hash=? AND account_id=? AND state='pending'""",
            (action,contact_hash,stamp,digest,account_id),
        ).rowcount
        if updated!=1:
            raise RuntimeError("customer_passage_confirmation_conflict")
    return {
        "ok":True,
        "confirmed":True,
        "action":action,
        "confirmedAt":stamp,
        "contactDetailsComplete":True,
    }


def verify_passage_confirmation(
    account_id: object,
    passage_token: object,
) -> dict:
    account_id=_account_id(account_id)
    row=_passage_row(account_id,passage_token)
    if str(row["state"])!="confirmed":
        raise PermissionError("customer_passage_not_confirmed")
    current=profile(account_id)
    expected=_contact_hash(account_id,current)
    if not hmac.compare_digest(str(row["contact_hash"] or ""),expected):
        raise PermissionError("customer_passage_contact_changed")
    return {
        "ok":True,
        "confirmed":True,
        "action":str(verified["action"]),
        "confirmedAt":str(verified["confirmedAt"]),
    }


def consume_passage_confirmation(
    account_id: object,
    passage_token: object,
) -> dict:
    account_id=_account_id(account_id)
    verified=verify_passage_confirmation(account_id,passage_token)
    row=_passage_row(account_id,passage_token)
    stamp=_now_iso()
    digest=str(row["passage_hash"])
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        removed=db.execute(
            """DELETE FROM customer_passage_confirmation
               WHERE passage_hash=? AND account_id=? AND state='confirmed'""",
            (digest,account_id),
        ).rowcount
        if removed!=1:
            raise RuntimeError("customer_passage_consume_conflict")
    return {
        "ok":True,
        "consumed":True,
        "action":str(row["action"]),
        "confirmedAt":str(row["confirmed_at"]),
        "consumedAt":stamp,
        "confirmationRetained":False,
    }


def profile(account_id: object) -> dict:
    account_id = _account_id(account_id)
    init_db()
    with _connect() as db:
        row = db.execute(
            """SELECT account_id,kind,profile_blob,wallet_code,created_at,updated_at
               FROM customer_account WHERE account_id=?""",
            (account_id,),
        ).fetchone()
        if not row:
            raise CustomerAccountError("customer_account_not_found")
        providers = [
            str(item["provider"])
            for item in db.execute(
                "SELECT provider FROM customer_identity WHERE account_id=? ORDER BY provider",
                (account_id,),
            ).fetchall()
        ]
    profile_data = _decrypt_profile(account_id, row["profile_blob"])
    wallet_code = str(row["wallet_code"] or "") or _ensure_wallet(account_id)
    wallet = referral_engine.account_summary(wallet_code)
    return {
        "ok": True,
        "accountId": account_id,
        "kind": str(row["kind"]),
        "displayName": str(profile_data.get("displayName") or ""),
        "email": str(profile_data.get("email") or ""),
        "companyName": str(profile_data.get("companyName") or ""),
        "siret": str(profile_data.get("siret") or ""),
        "phone": str(profile_data.get("phone") or ""),
        "addressLine1": str(profile_data.get("addressLine1") or ""),
        "addressLine2": str(profile_data.get("addressLine2") or ""),
        "postalCode": str(profile_data.get("postalCode") or ""),
        "city": str(profile_data.get("city") or ""),
        "contactDetailsComplete": _contact_complete(profile_data),
        "providers": providers,
        "loyalty": {
            "referralCode": wallet["code"],
            "currency": wallet["currency"],
            "balanceCents": int(wallet["balanceCents"]),
            "pendingCents": int(wallet["pendingCents"]),
            "earnedReferrals": int(wallet.get("earnedReferrals", 0)),
            "pendingReferrals": int(wallet.get("pendingReferrals", 0)),
        },
        "createdAt": str(row["created_at"]),
        "updatedAt": str(row["updated_at"]),
    }


def issue_session(account_id: object) -> dict:
    account_id = _account_id(account_id)
    profile(account_id)
    token = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    now = _now()
    expires = now + dt.timedelta(hours=SESSION_TTL_HOURS)
    init_db()
    with _connect() as db:
        db.execute(
            """INSERT INTO customer_session(
                 session_hash,account_id,created_at,expires_at,last_seen_at
               ) VALUES(?,?,?,?,?)""",
            (
                token_hash,
                account_id,
                now.isoformat(timespec="seconds"),
                expires.isoformat(timespec="seconds"),
                now.isoformat(timespec="seconds"),
            ),
        )
    return {
        "token": token,
        "accountId": account_id,
        "expiresAt": expires.isoformat(timespec="seconds"),
        "maxAge": SESSION_TTL_HOURS * 3600,
    }


def authenticate_session(token: object) -> str:
    raw = str(token or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", raw):
        raise PermissionError("customer_session_invalid")
    token_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    init_db()
    now = _now()
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT account_id,expires_at FROM customer_session WHERE session_hash=?",
            (token_hash,),
        ).fetchone()
        if not row:
            raise PermissionError("customer_session_invalid")
        expires = dt.datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00"))
        if now >= expires:
            db.execute("DELETE FROM customer_session WHERE session_hash=?", (token_hash,))
            raise PermissionError("customer_session_expired")
        db.execute(
            "UPDATE customer_session SET last_seen_at=? WHERE session_hash=?",
            (now.isoformat(timespec="seconds"), token_hash),
        )
        return str(row["account_id"])


def csrf_token(session_token: object) -> str:
    raw = str(session_token or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", raw):
        raise PermissionError("customer_session_invalid")
    return _hmac("csrf", raw)


def verify_csrf(session_token: object, supplied: object) -> bool:
    try:
        expected = csrf_token(session_token)
    except PermissionError:
        return False
    raw = str(supplied or "").strip()
    return bool(re.fullmatch(r"[0-9a-f]{64}", raw)) and hmac.compare_digest(expected, raw)


def close_session(token: object) -> None:
    raw = str(token or "").strip()
    if not raw:
        return
    token_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    init_db()
    with _connect() as db:
        db.execute("DELETE FROM customer_session WHERE session_hash=?", (token_hash,))
