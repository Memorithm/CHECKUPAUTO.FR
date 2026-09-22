from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import re
import secrets
import uuid

import analytics_store as analytics
import mobile_devices
import referral_engine


_CLAIM_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
_CLAIM_PREFIX = "rw_"
_DEFAULT_TTL_SECONDS = 1800
_MAX_TTL_SECONDS = 86400
_MAX_WALLETS_PER_INSTALLATION = 16


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _now_iso() -> str:
    return _now().isoformat(timespec="seconds")


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _account_id(value: object) -> str:
    raw = str(value or "").strip().lower()
    try:
        parsed = uuid.UUID(raw)
    except (ValueError, AttributeError) as exc:
        raise ValueError("accountId invalide") from exc
    if str(parsed) != raw:
        raise ValueError("accountId invalide")
    return raw


def _claim_token(value: object) -> str:
    raw = str(value or "").strip()
    if not _CLAIM_RE.fullmatch(raw) or not raw.startswith(_CLAIM_PREFIX):
        raise ValueError("claimToken invalide")
    return raw


def _ttl(value: object) -> int:
    try:
        ttl = int(value if value is not None else _DEFAULT_TTL_SECONDS)
    except (TypeError, ValueError) as exc:
        raise ValueError("ttlSeconds invalide") from exc
    if ttl < 60 or ttl > _MAX_TTL_SECONDS:
        raise ValueError("ttlSeconds invalide")
    return ttl


def init_db() -> None:
    referral_engine.init_db()
    with analytics.connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS referral_wallet_claim(
              token_hash TEXT PRIMARY KEY,
              account_id TEXT NOT NULL,
              created_at TEXT NOT NULL,
              expires_at TEXT NOT NULL,
              FOREIGN KEY(account_id) REFERENCES referral_accounts(id)
            );
            CREATE INDEX IF NOT EXISTS idx_referral_wallet_claim_account
              ON referral_wallet_claim(account_id,expires_at);
            CREATE TABLE IF NOT EXISTS referral_wallet_owner(
              account_id TEXT PRIMARY KEY,
              installation_hash TEXT NOT NULL,
              claimed_at TEXT NOT NULL,
              evidence_hash TEXT NOT NULL,
              FOREIGN KEY(account_id) REFERENCES referral_accounts(id)
            );
            CREATE INDEX IF NOT EXISTS idx_referral_wallet_owner_installation
              ON referral_wallet_owner(installation_hash,claimed_at);
            """
        )
    try:
        analytics.DB.chmod(0o600)
    except PermissionError:
        pass


def _active_account_by_code(db, code: object):
    clean = referral_engine.normalize_code(code)
    if not clean:
        raise ValueError("Code de parrainage invalide")
    row = db.execute(
        "SELECT id,code FROM referral_accounts WHERE code=? AND active=1",
        (clean,),
    ).fetchone()
    if not row:
        raise LookupError("Compte de parrainage introuvable")
    return row


def issue(code: object, ttl_seconds: object = _DEFAULT_TTL_SECONDS) -> dict:
    """Issue a one-time, high-entropy ownership claim for one referral wallet.

    The raw token is returned exactly once to the trusted caller. Only its SHA-256
    digest is persisted. Issuing a new claim revokes any still-pending claim for
    the same wallet so there is a single live transfer secret at a time.

    Wallet tokens have a dedicated ``rw_`` namespace. This prevents a consumer
    from accidentally treating a wallet claim as another mobile claim type while
    keeping the random payload at 256 bits of entropy.
    """
    ttl = _ttl(ttl_seconds)
    token = _CLAIM_PREFIX + secrets.token_urlsafe(32)
    token_hash = _hash(token)
    now_dt = _now()
    now = now_dt.isoformat(timespec="seconds")
    expires = (now_dt + datetime.timedelta(seconds=ttl)).isoformat(timespec="seconds")
    init_db()
    with analytics.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        account = _active_account_by_code(db, code)
        db.execute("DELETE FROM referral_wallet_claim WHERE expires_at<=?", (now,))
        db.execute("DELETE FROM referral_wallet_claim WHERE account_id=?", (account["id"],))
        db.execute(
            """INSERT INTO referral_wallet_claim(token_hash,account_id,created_at,expires_at)
               VALUES(?,?,?,?)""",
            (token_hash, account["id"], now, expires),
        )
    return {
        "claimToken": token,
        "claimType": "referral_wallet",
        "expiresAt": expires,
        "singleUse": True,
        "rawTokenPersisted": False,
    }


def _authenticate_installation(installation_id: object, registration_secret: object) -> str:
    installation = mobile_devices._install_id(installation_id)
    secret_hash = mobile_devices._hash(mobile_devices._secret(registration_secret))
    mobile_devices.init_db()
    with mobile_devices.connect() as db:
        row = mobile_devices._authenticated_installation(db, installation, secret_hash)
        if str(row["disabled_at"] or ""):
            raise PermissionError("identité mobile refusée")
    return installation


def consume(payload: dict) -> dict:
    """Bind a referral wallet to an authenticated mobile installation.

    Ownership is established only by possession of both the installation's
    registration secret and a fresh one-time wallet claim. The referral code is
    deliberately not accepted as ownership evidence because it is shareable.

    A single installation is deliberately bounded to the same maximum number of
    wallets accepted by the iOS read model. This keeps the server-side ownership
    graph and the mobile validation boundary consistent and prevents an otherwise
    valid installation from accumulating an unbounded wallet collection.
    """
    if not isinstance(payload, dict):
        raise ValueError("payload invalide")
    if set(payload) != {"installationId", "registrationSecret", "claimToken"}:
        raise ValueError("payload invalide")
    installation = _authenticate_installation(
        payload.get("installationId"),
        payload.get("registrationSecret"),
    )
    token = _claim_token(payload.get("claimToken"))
    token_hash = _hash(token)
    installation_hash = _hash(installation)
    now_dt = _now()
    now = now_dt.isoformat(timespec="seconds")
    expired = False
    account_id = ""

    init_db()
    with analytics.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        claim = db.execute(
            """SELECT c.account_id,c.expires_at,a.active
               FROM referral_wallet_claim c
               JOIN referral_accounts a ON a.id=c.account_id
               WHERE c.token_hash=?""",
            (token_hash,),
        ).fetchone()
        if not claim or not bool(claim["active"]):
            raise PermissionError("claim de cagnotte refusé")
        try:
            expires = datetime.datetime.fromisoformat(str(claim["expires_at"]))
        except ValueError as exc:
            raise PermissionError("claim de cagnotte refusé") from exc
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=datetime.timezone.utc)
        if expires <= now_dt:
            # Do not raise from inside the sqlite context manager: doing so would
            # roll back this physical deletion and leave the expired secret alive.
            db.execute("DELETE FROM referral_wallet_claim WHERE token_hash=?", (token_hash,))
            expired = True
        else:
            account_id = _account_id(claim["account_id"])
            owner = db.execute(
                "SELECT installation_hash FROM referral_wallet_owner WHERE account_id=?",
                (account_id,),
            ).fetchone()
            if owner and not hmac.compare_digest(str(owner["installation_hash"]), installation_hash):
                raise PermissionError("propriété de cagnotte déjà établie")
            if not owner:
                owned_count = int(
                    db.execute(
                        "SELECT COUNT(*) n FROM referral_wallet_owner WHERE installation_hash=?",
                        (installation_hash,),
                    ).fetchone()["n"]
                )
                if owned_count >= _MAX_WALLETS_PER_INSTALLATION:
                    raise PermissionError("limite de cagnottes mobiles atteinte")

            evidence = {
                "accountIdHash": _hash(account_id),
                "installationHash": installation_hash,
                "claimTokenHash": token_hash,
                "claimedAt": now,
            }
            evidence_hash = _hash(
                json.dumps(evidence, sort_keys=True, separators=(",", ":"))
            )
            db.execute(
                """INSERT INTO referral_wallet_owner(account_id,installation_hash,claimed_at,evidence_hash)
                   VALUES(?,?,?,?)
                   ON CONFLICT(account_id) DO UPDATE SET
                     claimed_at=excluded.claimed_at,evidence_hash=excluded.evidence_hash
                   WHERE referral_wallet_owner.installation_hash=excluded.installation_hash""",
                (account_id, installation_hash, now, evidence_hash),
            )
            db.execute("DELETE FROM referral_wallet_claim WHERE token_hash=?", (token_hash,))

    if expired:
        raise PermissionError("claim de cagnotte refusé")
    return {
        "ok": True,
        "accountId": account_id,
        "claimType": "referral_wallet",
        "claimedAt": now,
        "provenance": "authenticated_mobile_wallet_claim",
        "rawInstallationPersisted": False,
        "rawClaimTokenPersisted": False,
    }


def ownership_matches(account_id: object, installation_id: object) -> bool:
    account = _account_id(account_id)
    installation = mobile_devices._install_id(installation_id)
    expected = _hash(installation)
    init_db()
    with analytics.connect() as db:
        row = db.execute(
            "SELECT installation_hash FROM referral_wallet_owner WHERE account_id=?",
            (account,),
        ).fetchone()
    return bool(row) and hmac.compare_digest(str(row["installation_hash"]), expected)


def owned_account_ids(installation_id: object) -> list[str]:
    installation = mobile_devices._install_id(installation_id)
    digest = _hash(installation)
    init_db()
    with analytics.connect() as db:
        rows = db.execute(
            """SELECT o.account_id
               FROM referral_wallet_owner o
               JOIN referral_accounts a ON a.id=o.account_id
               WHERE o.installation_hash=? AND a.active=1
               ORDER BY o.claimed_at,o.account_id""",
            (digest,),
        ).fetchall()
    return [str(row["account_id"]) for row in rows]


def capability() -> dict:
    init_db()
    now = _now_iso()
    with analytics.connect() as db:
        owner_count = int(db.execute("SELECT COUNT(*) n FROM referral_wallet_owner").fetchone()["n"])
        live_claim_count = int(
            db.execute(
                "SELECT COUNT(*) n FROM referral_wallet_claim WHERE expires_at>?",
                (now,),
            ).fetchone()["n"]
        )
    return {
        "bound": True,
        "provenance": "authenticated_mobile_wallet_claim",
        "claimType": "referral_wallet",
        "claimTokenPrefix": _CLAIM_PREFIX,
        "claimEntropyBits": 256,
        "singleUseClaims": True,
        "maxWalletsPerInstallation": _MAX_WALLETS_PER_INSTALLATION,
        "rawClaimTokenPersisted": False,
        "rawInstallationPersisted": False,
        "ownerEvidenceCount": owner_count,
        "liveClaimCount": live_claim_count,
    }
