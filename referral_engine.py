from __future__ import annotations

import datetime
import os
import re
import secrets
import sqlite3
import uuid

import analytics_store as analytics

_PROVIDER = "mercure-rdv"
_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{3,23}$")
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_ALLOWED_REWARD_STATUS = {"pending", "earned", "cancelled", "reversed"}


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def configured_reward_cents() -> int:
    raw = str(os.environ.get("CYBERCHECK_REFERRAL_REWARD_CENTS", "500") or "500").strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("CYBERCHECK_REFERRAL_REWARD_CENTS invalide") from exc
    if value < 1 or value > 5000:
        raise ValueError("CYBERCHECK_REFERRAL_REWARD_CENTS invalide")
    return value


def normalize_code(value: object) -> str:
    raw = str(value or "").strip().upper().replace("_", "-")
    raw = re.sub(r"[^A-Z0-9-]", "", raw)
    raw = re.sub(r"-{2,}", "-", raw).strip("-")
    if not raw or not _CODE_RE.fullmatch(raw):
        return ""
    return raw


def generate_code() -> str:
    return "CA-" + "".join(secrets.choice(_ALPHABET) for _ in range(8))


def init_db() -> None:
    with analytics.connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS referral_accounts(
              id TEXT PRIMARY KEY,
              code TEXT NOT NULL UNIQUE,
              created_at TEXT NOT NULL,
              active INTEGER NOT NULL DEFAULT 1,
              reward_cents INTEGER NOT NULL,
              currency TEXT NOT NULL DEFAULT 'EUR'
            );
            CREATE TABLE IF NOT EXISTS referral_rewards(
              provider TEXT NOT NULL,
              external_id TEXT NOT NULL,
              account_id TEXT NOT NULL,
              referral_code TEXT NOT NULL,
              status TEXT NOT NULL,
              reward_cents INTEGER NOT NULL,
              attribution_token TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              earned_at TEXT,
              cancelled_at TEXT,
              reversed_at TEXT,
              PRIMARY KEY(provider, external_id),
              FOREIGN KEY(account_id) REFERENCES referral_accounts(id)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_referral_reward_token
              ON referral_rewards(attribution_token)
              WHERE attribution_token<>'';
            CREATE INDEX IF NOT EXISTS idx_referral_reward_account
              ON referral_rewards(account_id, status);
            CREATE TABLE IF NOT EXISTS referral_ledger(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              account_id TEXT NOT NULL,
              kind TEXT NOT NULL,
              amount_cents INTEGER NOT NULL,
              reference TEXT NOT NULL,
              created_at TEXT NOT NULL,
              note TEXT NOT NULL DEFAULT '',
              UNIQUE(account_id, kind, reference),
              FOREIGN KEY(account_id) REFERENCES referral_accounts(id)
            );
            CREATE INDEX IF NOT EXISTS idx_referral_ledger_account
              ON referral_ledger(account_id, created_at);
            """
        )
    analytics.DB.chmod(0o600)


def create_account(code: object = "", reward_cents: int | None = None) -> dict:
    init_db()
    clean = normalize_code(code)
    if code and not clean:
        raise ValueError("Code de parrainage invalide")
    reward = configured_reward_cents() if reward_cents is None else int(reward_cents)
    if reward < 1 or reward > 5000:
        raise ValueError("Récompense de parrainage invalide")
    for _ in range(12):
        candidate = clean or generate_code()
        account_id = str(uuid.uuid4())
        created = now_iso()
        try:
            with analytics.connect() as db:
                db.execute(
                    "INSERT INTO referral_accounts(id,code,created_at,active,reward_cents,currency) VALUES(?,?,?,?,?,?)",
                    (account_id, candidate, created, 1, reward, "EUR"),
                )
            return account_summary(candidate)
        except sqlite3.IntegrityError as exc:
            if clean:
                raise ValueError("Ce code de parrainage existe déjà") from exc
    raise RuntimeError("Impossible de générer un code de parrainage unique")


def _account_by_code(db, code: str):
    return db.execute(
        "SELECT * FROM referral_accounts WHERE code=? AND active=1",
        (code,),
    ).fetchone()


def valid_code_or_empty(value: object) -> str:
    code = normalize_code(value)
    if not code:
        return ""
    init_db()
    with analytics.connect() as db:
        return code if _account_by_code(db, code) else ""


def record_pending(
    code: object,
    provider: str,
    external_id: object,
    attribution_token: object = "",
) -> dict | None:
    code = valid_code_or_empty(code)
    external_id = str(external_id or "").strip()[:120]
    token = str(attribution_token or "").strip()[:120]
    provider = str(provider or _PROVIDER).strip()[:60] or _PROVIDER
    if not code or not external_id:
        return None
    init_db()
    now = now_iso()
    with analytics.connect() as db:
        account = _account_by_code(db, code)
        if not account:
            return None
        if token:
            existing = db.execute(
                "SELECT * FROM referral_rewards WHERE attribution_token=?",
                (token,),
            ).fetchone()
            if existing:
                if (
                    existing["status"] == "pending"
                    and (existing["provider"] != provider or existing["external_id"] != external_id)
                ):
                    conflict = db.execute(
                        "SELECT 1 FROM referral_rewards WHERE provider=? AND external_id=?",
                        (provider, external_id),
                    ).fetchone()
                    if not conflict:
                        db.execute(
                            "UPDATE referral_rewards SET provider=?,external_id=?,updated_at=? WHERE attribution_token=?",
                            (provider, external_id, now, token),
                        )
                        existing = db.execute(
                            "SELECT * FROM referral_rewards WHERE attribution_token=?",
                            (token,),
                        ).fetchone()
                return dict(existing)
        existing = db.execute(
            "SELECT * FROM referral_rewards WHERE provider=? AND external_id=?",
            (provider, external_id),
        ).fetchone()
        if existing:
            return dict(existing)
        db.execute(
            """INSERT INTO referral_rewards(
               provider,external_id,account_id,referral_code,status,reward_cents,
               attribution_token,created_at,updated_at
               ) VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                provider,
                external_id,
                account["id"],
                code,
                "pending",
                int(account["reward_cents"]),
                token,
                now,
                now,
            ),
        )
        row = db.execute(
            "SELECT * FROM referral_rewards WHERE provider=? AND external_id=?",
            (provider, external_id),
        ).fetchone()
        return dict(row)


def complete_control(provider: str, external_id: object) -> dict | None:
    init_db()
    provider = str(provider or _PROVIDER).strip()[:60] or _PROVIDER
    external_id = str(external_id or "").strip()[:120]
    if not external_id:
        return None
    now = now_iso()
    with analytics.connect() as db:
        row = db.execute(
            "SELECT * FROM referral_rewards WHERE provider=? AND external_id=?",
            (provider, external_id),
        ).fetchone()
        if not row:
            return None
        if row["status"] == "earned":
            return dict(row)
        if row["status"] != "pending":
            return dict(row)
        reference = f"{provider}:{external_id}"
        db.execute(
            "UPDATE referral_rewards SET status='earned',updated_at=?,earned_at=? WHERE provider=? AND external_id=?",
            (now, now, provider, external_id),
        )
        db.execute(
            """INSERT OR IGNORE INTO referral_ledger(
               account_id,kind,amount_cents,reference,created_at,note
               ) VALUES(?,?,?,?,?,?)""",
            (
                row["account_id"],
                "earn",
                int(row["reward_cents"]),
                reference,
                now,
                "Contrôle réalisé via parrainage",
            ),
        )
        updated = db.execute(
            "SELECT * FROM referral_rewards WHERE provider=? AND external_id=?",
            (provider, external_id),
        ).fetchone()
        return dict(updated)


def cancel_pending(provider: str, external_id: object) -> dict | None:
    init_db()
    provider = str(provider or _PROVIDER).strip()[:60] or _PROVIDER
    external_id = str(external_id or "").strip()[:120]
    if not external_id:
        return None
    now = now_iso()
    with analytics.connect() as db:
        row = db.execute(
            "SELECT * FROM referral_rewards WHERE provider=? AND external_id=?",
            (provider, external_id),
        ).fetchone()
        if not row:
            return None
        if row["status"] == "pending":
            db.execute(
                "UPDATE referral_rewards SET status='cancelled',updated_at=?,cancelled_at=? WHERE provider=? AND external_id=?",
                (now, now, provider, external_id),
            )
        updated = db.execute(
            "SELECT * FROM referral_rewards WHERE provider=? AND external_id=?",
            (provider, external_id),
        ).fetchone()
        return dict(updated)


def redeem(code: object, amount_cents: int, reference: object) -> dict:
    init_db()
    code = normalize_code(code)
    reference = str(reference or "").strip()[:120]
    amount = int(amount_cents)
    if not code or amount <= 0 or amount > 100000 or not reference:
        raise ValueError("Utilisation de cagnotte invalide")
    now = now_iso()
    with analytics.connect() as db:
        account = _account_by_code(db, code)
        if not account:
            raise ValueError("Code de parrainage inconnu")
        balance = int(
            db.execute(
                "SELECT COALESCE(SUM(amount_cents),0) balance FROM referral_ledger WHERE account_id=?",
                (account["id"],),
            ).fetchone()["balance"]
        )
        if amount > balance:
            raise ValueError("Solde de cagnotte insuffisant")
        try:
            db.execute(
                """INSERT INTO referral_ledger(
                   account_id,kind,amount_cents,reference,created_at,note
                   ) VALUES(?,?,?,?,?,?)""",
                (account["id"], "redeem", -amount, reference, now, "Crédit utilisé"),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("Cette utilisation de cagnotte a déjà été enregistrée") from exc
    return account_summary(code)


def account_summary(code: object) -> dict:
    init_db()
    code = normalize_code(code)
    if not code:
        raise ValueError("Code de parrainage invalide")
    with analytics.connect() as db:
        account = db.execute(
            "SELECT * FROM referral_accounts WHERE code=?",
            (code,),
        ).fetchone()
        if not account:
            raise ValueError("Code de parrainage inconnu")
        balance = int(
            db.execute(
                "SELECT COALESCE(SUM(amount_cents),0) balance FROM referral_ledger WHERE account_id=?",
                (account["id"],),
            ).fetchone()["balance"]
        )
        counts = {
            row["status"]: int(row["n"])
            for row in db.execute(
                "SELECT status,COUNT(*) n FROM referral_rewards WHERE account_id=? GROUP BY status",
                (account["id"],),
            )
        }
        pending_cents = int(
            db.execute(
                "SELECT COALESCE(SUM(reward_cents),0) total FROM referral_rewards WHERE account_id=? AND status='pending'",
                (account["id"],),
            ).fetchone()["total"]
        )
        ledger = [
            dict(row)
            for row in db.execute(
                """SELECT kind,amount_cents amountCents,reference,created_at createdAt,note
                   FROM referral_ledger WHERE account_id=?
                   ORDER BY id DESC LIMIT 50""",
                (account["id"],),
            )
        ]
        return {
            "id": account["id"],
            "code": account["code"],
            "active": bool(account["active"]),
            "currency": account["currency"],
            "rewardCents": int(account["reward_cents"]),
            "balanceCents": balance,
            "pendingCents": pending_cents,
            "earnedReferrals": counts.get("earned", 0),
            "pendingReferrals": counts.get("pending", 0),
            "cancelledReferrals": counts.get("cancelled", 0),
            "ledger": ledger,
        }


def list_accounts(limit: int = 100) -> list[dict]:
    init_db()
    limit = max(1, min(int(limit), 500))
    with analytics.connect() as db:
        codes = [
            row["code"]
            for row in db.execute(
                "SELECT code FROM referral_accounts ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        ]
    return [account_summary(code) for code in codes]


def reward_status(provider: str, external_id: object) -> dict | None:
    init_db()
    with analytics.connect() as db:
        row = db.execute(
            "SELECT * FROM referral_rewards WHERE provider=? AND external_id=?",
            (str(provider or _PROVIDER), str(external_id or "")),
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        if result["status"] not in _ALLOWED_REWARD_STATUS:
            raise RuntimeError("État de parrainage incohérent")
        return result
