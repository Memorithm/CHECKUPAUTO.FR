"""Local customer e-mail/password authentication.

Passwords are memory-hard hashed with scrypt. Raw passwords and raw one-time
verification/reset tokens are never persisted. The account e-mail remains in the
existing encrypted customer profile and is looked up through the existing HMAC.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import re
import secrets
import uuid

import customer_accounts as accounts

PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128
SCRYPT_N = 1 << 15
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32
SCRYPT_MAXMEM = 64 * 1024 * 1024
TOKEN_TTL_MINUTES = 30
LOGIN_FAILURE_LIMIT = 5
LOGIN_LOCK_MINUTES = 15
PENDING_ACCOUNT_TTL_HOURS = 24


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(raw: str) -> bytes:
    return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))


def _password(value: object) -> str:
    raw = str(value or "")
    if not PASSWORD_MIN_LENGTH <= len(raw) <= PASSWORD_MAX_LENGTH:
        raise accounts.CustomerAccountError("customer_password_policy_invalid")
    if any(ord(ch) < 32 for ch in raw):
        raise accounts.CustomerAccountError("customer_password_policy_invalid")
    return raw


def _login_password(value: object) -> str:
    raw = str(value or "")
    if not raw or len(raw) > PASSWORD_MAX_LENGTH or any(ord(ch) < 32 for ch in raw):
        return ""
    return raw


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P,
        dklen=SCRYPT_DKLEN, maxmem=SCRYPT_MAXMEM,
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def _verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = str(encoded or "").split("$", 5)
        if algorithm != "scrypt":
            return False
        n_i, r_i, p_i = int(n), int(r), int(p)
        if (n_i, r_i, p_i) != (SCRYPT_N, SCRYPT_R, SCRYPT_P):
            return False
        salt_raw = _unb64(salt)
        expected_raw = _unb64(expected)
        if len(salt_raw) != 16 or len(expected_raw) != SCRYPT_DKLEN:
            return False
        actual = hashlib.scrypt(
            password.encode("utf-8"), salt=salt_raw, n=n_i, r=r_i, p=p_i,
            dklen=SCRYPT_DKLEN, maxmem=SCRYPT_MAXMEM,
        )
        return hmac.compare_digest(actual, expected_raw)
    except (ValueError, TypeError):
        return False


def _dummy_verify(password: str) -> None:
    # Keep the missing-account path computationally comparable to a real login.
    hashlib.scrypt(
        (password or "invalid-password").encode("utf-8"),
        salt=b"checkupauto-dummy", n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P,
        dklen=SCRYPT_DKLEN, maxmem=SCRYPT_MAXMEM,
    )


def _token_hash(token: object) -> str:
    raw = str(token or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", raw):
        raise PermissionError("customer_password_token_invalid")
    return hashlib.sha256(raw.encode("ascii")).hexdigest()


def _expiry(minutes: int = TOKEN_TTL_MINUTES) -> str:
    return (accounts._now() + dt.timedelta(minutes=minutes)).isoformat(timespec="seconds")


def _cleanup_tokens(db, now: str) -> None:
    db.execute("DELETE FROM customer_password_token WHERE expires_at<? OR consumed_at<>''", (now,))


def _cleanup_pending_accounts(db, now_dt: dt.datetime) -> None:
    cutoff=(now_dt-dt.timedelta(hours=PENDING_ACCOUNT_TTL_HOURS)).isoformat(timespec="seconds")
    db.execute(
        """DELETE FROM customer_account
           WHERE account_id IN (
             SELECT c.account_id FROM customer_password_credential c
             WHERE c.verified_at='' AND c.created_at<?
               AND NOT EXISTS (
                 SELECT 1 FROM customer_identity i WHERE i.account_id=c.account_id
               )
           )""",
        (cutoff,),
    )


def _insert_token(db, account_id: str, purpose: str, now: str) -> str:
    raw = secrets.token_urlsafe(32)
    digest = hashlib.sha256(raw.encode("ascii")).hexdigest()
    db.execute("DELETE FROM customer_password_token WHERE account_id=? AND purpose=?", (account_id, purpose))
    db.execute(
        """INSERT INTO customer_password_token(
             token_hash,account_id,purpose,created_at,expires_at,consumed_at
           ) VALUES(?,?,?,?,?,'')""",
        (digest, account_id, purpose, now, _expiry()),
    )
    return raw


def begin_registration(email: object, display_name: object, password: object) -> dict:
    clean_email = accounts._email(email)
    # Identity is completed in the authenticated profile, not inferred from e-mail.
    clean_name = "" if display_name is None or display_name == "" else accounts._display_name(display_name)
    clean_password = _password(password)
    if hmac.compare_digest(clean_password.casefold(), clean_email.casefold()):
        raise accounts.CustomerAccountError("customer_password_policy_invalid")
    encoded = _hash_password(clean_password)
    email_hash = accounts._hmac("email", clean_email)
    accounts.init_db()
    now_dt = accounts._now()
    now = now_dt.isoformat(timespec="seconds")
    purpose = "verify"

    with accounts._connect() as db:
        db.execute("BEGIN IMMEDIATE")
        _cleanup_tokens(db, now)
        _cleanup_pending_accounts(db, now_dt)
        row = db.execute(
            "SELECT account_id FROM customer_account WHERE email_hash=?", (email_hash,)
        ).fetchone()
        if row:
            # Never attach or replace a password on an existing account from an
            # unauthenticated sign-up form. The mailbox owner instead receives a
            # one-time link to choose the password (reset flow), so an attacker
            # cannot pre-seed a password on a federated or pending account.
            account_id = str(row["account_id"])
            purpose = "reset"
            db.execute(
                "DELETE FROM customer_password_token WHERE account_id=? AND purpose='verify'",
                (account_id,),
            )
        else:
            account_id = str(uuid.uuid4())
            encrypted = accounts._encrypt_profile(account_id, {
                "email": clean_email,
                "displayName": clean_name,
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
                """INSERT INTO customer_password_credential(
                     account_id,password_hash,verified_at,failed_attempts,locked_until,
                     created_at,updated_at,last_login_at
                   ) VALUES(?,?,'',0,'',?,?,'')""",
                (account_id, encoded, now, now),
            )
        token = _insert_token(db, account_id, purpose, now)

    return {
        "ok": True,
        "email": clean_email,
        "token": token,
        "purpose": purpose,
        "expiresAt": _expiry(),
    }


def verify_registration(token: object) -> dict:
    digest = _token_hash(token)
    accounts.init_db()
    now_dt = accounts._now()
    now = now_dt.isoformat(timespec="seconds")
    with accounts._connect() as db:
        db.execute("BEGIN IMMEDIATE")
        _cleanup_tokens(db, now)
        row = db.execute(
            """SELECT account_id,expires_at,consumed_at FROM customer_password_token
               WHERE token_hash=? AND purpose='verify'""",
            (digest,),
        ).fetchone()
        if not row or str(row["consumed_at"] or ""):
            raise PermissionError("customer_password_token_invalid")
        expires = dt.datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00"))
        if now_dt >= expires:
            raise PermissionError("customer_password_token_expired")
        account_id = str(row["account_id"])
        updated = db.execute(
            """UPDATE customer_password_credential
               SET verified_at=CASE WHEN verified_at='' THEN ? ELSE verified_at END,
                   failed_attempts=0,locked_until='',updated_at=?
               WHERE account_id=?""",
            (now, now, account_id),
        ).rowcount
        if updated != 1:
            raise PermissionError("customer_password_token_invalid")
        db.execute("UPDATE customer_password_token SET consumed_at=? WHERE token_hash=?", (now, digest))
        db.execute("DELETE FROM customer_password_token WHERE account_id=? AND purpose='verify' AND token_hash<>?", (account_id, digest))
    accounts._ensure_wallet(account_id)
    return accounts.profile(account_id)


def authenticate(email: object, password: object) -> dict:
    raw_password = _login_password(password)
    try:
        clean_email = accounts._email(email)
        email_hash = accounts._hmac("email", clean_email)
    except accounts.CustomerAccountError:
        _dummy_verify(raw_password)
        raise PermissionError("customer_login_invalid") from None
    if not raw_password:
        _dummy_verify(raw_password)
        raise PermissionError("customer_login_invalid")

    accounts.init_db()
    now_dt = accounts._now()
    now = now_dt.isoformat(timespec="seconds")
    with accounts._connect() as db:
        row = db.execute(
            """SELECT a.account_id,c.password_hash,c.verified_at,c.failed_attempts,c.locked_until
               FROM customer_account a
               JOIN customer_password_credential c ON c.account_id=a.account_id
               WHERE a.email_hash=?""",
            (email_hash,),
        ).fetchone()
        if not row:
            _dummy_verify(raw_password)
            raise PermissionError("customer_login_invalid")
        account_id = str(row["account_id"])
        locked_until = str(row["locked_until"] or "")
        locked = False
        if locked_until:
            try:
                locked = now_dt < dt.datetime.fromisoformat(locked_until.replace("Z", "+00:00"))
            except ValueError:
                locked = True
        valid = _verify_password(raw_password, str(row["password_hash"] or ""))
        if locked or not valid:
            failures = int(row["failed_attempts"] or 0) + 1
            new_lock = locked_until
            if failures >= LOGIN_FAILURE_LIMIT:
                new_lock = (now_dt + dt.timedelta(minutes=LOGIN_LOCK_MINUTES)).isoformat(timespec="seconds")
            db.execute(
                "UPDATE customer_password_credential SET failed_attempts=?,locked_until=?,updated_at=? WHERE account_id=?",
                (failures, new_lock, now, account_id),
            )
            db.commit()
            raise PermissionError("customer_login_invalid")
        if not str(row["verified_at"] or ""):
            raise accounts.CustomerAccountError("customer_email_not_verified")
        db.execute(
            """UPDATE customer_password_credential
               SET failed_attempts=0,locked_until='',last_login_at=?,updated_at=?
               WHERE account_id=?""",
            (now, now, account_id),
        )
    return accounts.profile(account_id)


def begin_reset(email: object) -> dict:
    try:
        clean_email = accounts._email(email)
        email_hash = accounts._hmac("email", clean_email)
    except accounts.CustomerAccountError:
        return {"ok": True, "deliver": False}
    accounts.init_db()
    now = accounts._now_iso()
    with accounts._connect() as db:
        db.execute("BEGIN IMMEDIATE")
        _cleanup_tokens(db, now)
        row = db.execute(
            """SELECT a.account_id FROM customer_account a
               JOIN customer_password_credential c ON c.account_id=a.account_id
               WHERE a.email_hash=? AND c.verified_at<>''""",
            (email_hash,),
        ).fetchone()
        if not row:
            return {"ok": True, "deliver": False}
        token = _insert_token(db, str(row["account_id"]), "reset", now)
    return {"ok": True, "deliver": True, "email": clean_email, "token": token, "expiresAt": _expiry()}


def reset_password(token: object, password: object) -> dict:
    digest = _token_hash(token)
    clean_password = _password(password)
    encoded = _hash_password(clean_password)
    accounts.init_db()
    now_dt = accounts._now()
    now = now_dt.isoformat(timespec="seconds")
    with accounts._connect() as db:
        db.execute("BEGIN IMMEDIATE")
        _cleanup_tokens(db, now)
        row = db.execute(
            """SELECT account_id,expires_at,consumed_at FROM customer_password_token
               WHERE token_hash=? AND purpose='reset'""",
            (digest,),
        ).fetchone()
        if not row or str(row["consumed_at"] or ""):
            raise PermissionError("customer_password_token_invalid")
        expires = dt.datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00"))
        if now_dt >= expires:
            raise PermissionError("customer_password_token_expired")
        account_id = str(row["account_id"])
        updated = db.execute(
            """UPDATE customer_password_credential
               SET password_hash=?,verified_at=CASE WHEN verified_at='' THEN ? ELSE verified_at END,
                   failed_attempts=0,locked_until='',updated_at=?
               WHERE account_id=?""",
            (encoded, now, now, account_id),
        ).rowcount
        if updated == 0:
            account_exists = db.execute(
                "SELECT 1 FROM customer_account WHERE account_id=?", (account_id,)
            ).fetchone()
            if not account_exists:
                raise PermissionError("customer_password_token_invalid")
            # Mailbox ownership was proven by the one-time link: the owner of a
            # federated account may add a password here.
            db.execute(
                """INSERT INTO customer_password_credential(
                     account_id,password_hash,verified_at,failed_attempts,locked_until,
                     created_at,updated_at,last_login_at
                   ) VALUES(?,?,?,0,'',?,?,'')""",
                (account_id, encoded, now, now, now),
            )
        elif updated != 1:
            raise PermissionError("customer_password_token_invalid")
        db.execute("DELETE FROM customer_session WHERE account_id=?", (account_id,))
        db.execute("UPDATE customer_password_token SET consumed_at=? WHERE token_hash=?", (now, digest))
        db.execute("DELETE FROM customer_password_token WHERE account_id=? AND purpose='reset' AND token_hash<>?", (account_id, digest))
    accounts._ensure_wallet(account_id)
    return accounts.profile(account_id)


def status(account_id: object) -> dict:
    clean_id = accounts._account_id(account_id)
    accounts.init_db()
    with accounts._connect() as db:
        row = db.execute(
            "SELECT verified_at,created_at,updated_at,last_login_at FROM customer_password_credential WHERE account_id=?",
            (clean_id,),
        ).fetchone()
    return {
        "configured": bool(row),
        "verified": bool(row and str(row["verified_at"] or "")),
        "createdAt": str(row["created_at"] or "") if row else "",
        "updatedAt": str(row["updated_at"] or "") if row else "",
        "lastLoginAt": str(row["last_login_at"] or "") if row else "",
    }
