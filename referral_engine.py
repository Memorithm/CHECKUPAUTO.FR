from __future__ import annotations

import datetime
import hashlib
import json
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


def _reward_ledger_reference(provider: str, external_id: str) -> str:
    """Build an opaque, unambiguous ledger id for one provider booking key."""
    provider_bytes = str(provider).encode("utf-8")
    external_bytes = str(external_id).encode("utf-8")
    payload = (
        len(provider_bytes).to_bytes(4, "big")
        + provider_bytes
        + len(external_bytes).to_bytes(4, "big")
        + external_bytes
    )
    return "reward:" + hashlib.sha256(payload).hexdigest()


def _legacy_reward_ledger_reference(provider: str, external_id: str) -> str:
    return f"{provider}:{external_id}"


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
            CREATE TABLE IF NOT EXISTS referral_ledger_checkpoint(
              account_id TEXT PRIMARY KEY,
              balance_cents INTEGER NOT NULL DEFAULT 0,
              compacted_entries INTEGER NOT NULL DEFAULT 0,
              updated_at TEXT NOT NULL,
              evidence_hash TEXT NOT NULL,
              FOREIGN KEY(account_id) REFERENCES referral_accounts(id)
            );
            CREATE TABLE IF NOT EXISTS referral_compacted_reward_evidence(
              account_id TEXT NOT NULL,
              reference TEXT NOT NULL,
              amount_cents INTEGER NOT NULL,
              reversed INTEGER NOT NULL DEFAULT 0,
              compacted_at TEXT NOT NULL,
              evidence_hash TEXT NOT NULL,
              PRIMARY KEY(account_id,reference),
              FOREIGN KEY(account_id) REFERENCES referral_accounts(id)
            );
            CREATE TABLE IF NOT EXISTS referral_redeem_tombstone(
              account_id TEXT NOT NULL,
              reference_hash TEXT NOT NULL,
              amount_cents INTEGER NOT NULL,
              compacted_at TEXT NOT NULL,
              evidence_hash TEXT NOT NULL,
              PRIMARY KEY(account_id,reference_hash),
              FOREIGN KEY(account_id) REFERENCES referral_accounts(id)
            );
            """
        )
        db.executescript(
            """
            -- Never DROP these invariant triggers during normal init: concurrent
            -- callers could otherwise observe a missing trigger or race on CREATE.
            CREATE TRIGGER IF NOT EXISTS trg_referral_ledger_nonnegative
              BEFORE INSERT ON referral_ledger
              WHEN NEW.amount_cents < 0
               AND NEW.kind <> 'reverse'
               AND (
                 COALESCE((
                   SELECT balance_cents FROM referral_ledger_checkpoint
                   WHERE account_id=NEW.account_id
                 ),0)
                 + COALESCE((
                   SELECT SUM(amount_cents) FROM referral_ledger
                   WHERE account_id=NEW.account_id
                 ),0)
                 + NEW.amount_cents
               ) < 0
            BEGIN
              SELECT RAISE(ABORT, 'referral balance would be negative');
            END;

            CREATE TRIGGER IF NOT EXISTS trg_referral_ledger_reverse_matches_earn
              BEFORE INSERT ON referral_ledger
              WHEN NEW.kind = 'reverse'
               AND NOT EXISTS(
                 SELECT 1 FROM referral_ledger
                 WHERE account_id=NEW.account_id
                   AND kind='earn'
                   AND reference=NEW.reference
                   AND amount_cents=-NEW.amount_cents
               )
               AND NOT EXISTS(
                 SELECT 1 FROM referral_compacted_reward_evidence
                 WHERE account_id=NEW.account_id
                   AND reference=NEW.reference
                   AND amount_cents=-NEW.amount_cents
                   AND reversed=0
               )
            BEGIN
              SELECT RAISE(ABORT, 'referral reversal must match earn');
            END;
            """
        )
    analytics.DB.chmod(0o600)


def _checkpoint_balance_locked(db, account_id: str) -> int:
    row = db.execute(
        "SELECT balance_cents FROM referral_ledger_checkpoint WHERE account_id=?",
        (account_id,),
    ).fetchone()
    return int(row["balance_cents"]) if row else 0


def _wallet_balance_locked(db, account_id: str) -> int:
    live = int(
        db.execute(
            "SELECT COALESCE(SUM(amount_cents),0) balance FROM referral_ledger WHERE account_id=?",
            (account_id,),
        ).fetchone()["balance"]
    )
    return _checkpoint_balance_locked(db, account_id) + live


def _reference_hash(reference: str) -> str:
    return hashlib.sha256(str(reference).encode("utf-8")).hexdigest()


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
        db.execute("BEGIN IMMEDIATE")
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
        reference = _reward_ledger_reference(provider, external_id)
        changed = db.execute(
            """UPDATE referral_rewards
               SET status='earned',updated_at=?,earned_at=?
               WHERE provider=? AND external_id=? AND status='pending'""",
            (now, now, provider, external_id),
        )
        if changed.rowcount != 1:
            updated = db.execute(
                "SELECT * FROM referral_rewards WHERE provider=? AND external_id=?",
                (provider, external_id),
            ).fetchone()
            return dict(updated) if updated else None
        try:
            db.execute(
                """INSERT INTO referral_ledger(
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
        except sqlite3.IntegrityError as exc:
            raise RuntimeError("Intégrité du crédit de parrainage incohérente") from exc
        updated = db.execute(
            "SELECT * FROM referral_rewards WHERE provider=? AND external_id=?",
            (provider, external_id),
        ).fetchone()
        return dict(updated)


def _earned_reference_locked(db, row, provider: str, external_id: str, reward_cents: int) -> str:
    reference = _reward_ledger_reference(provider, external_id)
    earned = db.execute(
        """SELECT amount_cents FROM referral_ledger
           WHERE account_id=? AND kind='earn' AND reference=?""",
        (row["account_id"], reference),
    ).fetchone()
    if earned:
        if int(earned["amount_cents"]) != reward_cents:
            raise RuntimeError("Intégrité du crédit de parrainage incohérente")
        return reference

    compacted = db.execute(
        """SELECT amount_cents FROM referral_compacted_reward_evidence
           WHERE account_id=? AND reference=?""",
        (row["account_id"], reference),
    ).fetchone()
    if compacted:
        if int(compacted["amount_cents"]) != reward_cents:
            raise RuntimeError("Intégrité du crédit de parrainage incohérente")
        return reference

    legacy_reference = _legacy_reward_ledger_reference(provider, external_id)
    legacy_earned = db.execute(
        """SELECT amount_cents FROM referral_ledger
           WHERE account_id=? AND kind='earn' AND reference=?""",
        (row["account_id"], legacy_reference),
    ).fetchone()
    if not legacy_earned or int(legacy_earned["amount_cents"]) != reward_cents:
        raise RuntimeError("Intégrité du crédit de parrainage incohérente")

    legacy_candidates = db.execute(
        """SELECT provider,external_id FROM referral_rewards
           WHERE account_id=? AND status IN ('earned','reversed')""",
        (row["account_id"],),
    ).fetchall()
    matching = [
        candidate
        for candidate in legacy_candidates
        if _legacy_reward_ledger_reference(candidate["provider"], candidate["external_id"])
        == legacy_reference
    ]
    if len(matching) != 1 or (
        matching[0]["provider"] != provider or matching[0]["external_id"] != external_id
    ):
        raise RuntimeError("Référence historique de parrainage ambiguë")
    return legacy_reference


def _reverse_earned_locked(db, row, provider: str, external_id: str, now: str) -> dict:
    reward_cents = int(row["reward_cents"])
    reference = _earned_reference_locked(db, row, provider, external_id, reward_cents)
    existing_reverse = db.execute(
        """SELECT 1 FROM referral_ledger
           WHERE account_id=? AND kind='reverse' AND reference=?""",
        (row["account_id"], reference),
    ).fetchone()
    compacted_reverse = db.execute(
        """SELECT reversed FROM referral_compacted_reward_evidence
           WHERE account_id=? AND reference=?""",
        (row["account_id"], reference),
    ).fetchone()
    if existing_reverse or (compacted_reverse and bool(compacted_reverse["reversed"])):
        raise RuntimeError("Intégrité de l'annulation de parrainage incohérente")
    try:
        db.execute(
            """INSERT INTO referral_ledger(
               account_id,kind,amount_cents,reference,created_at,note
               ) VALUES(?,?,?,?,?,?)""",
            (
                row["account_id"],
                "reverse",
                -reward_cents,
                reference,
                now,
                "Crédit de parrainage annulé",
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise RuntimeError("Intégrité de l'annulation de parrainage incohérente") from exc
    db.execute(
        """UPDATE referral_compacted_reward_evidence
           SET reversed=1,compacted_at=?
           WHERE account_id=? AND reference=?""",
        (now, row["account_id"], reference),
    )
    changed = db.execute(
        """UPDATE referral_rewards
           SET status='reversed',updated_at=?,reversed_at=?
           WHERE provider=? AND external_id=? AND status='earned'""",
        (now, now, provider, external_id),
    )
    if changed.rowcount != 1:
        raise RuntimeError("État de parrainage incohérent")
    updated = db.execute(
        "SELECT * FROM referral_rewards WHERE provider=? AND external_id=?",
        (provider, external_id),
    ).fetchone()
    return dict(updated)


def cancel_pending(provider: str, external_id: object) -> dict | None:
    """Cancel pending credit or reverse an earned credit after provider correction.

    A provider can correct a completed appointment to cancelled/no-show after a
    referral credit has already been spent. Reversal entries may therefore take
    the wallet below zero: the debt remains visible and future redemptions stay
    blocked until later earnings restore a positive balance.
    """
    init_db()
    provider = str(provider or _PROVIDER).strip()[:60] or _PROVIDER
    external_id = str(external_id or "").strip()[:120]
    if not external_id:
        return None
    now = now_iso()
    with analytics.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT * FROM referral_rewards WHERE provider=? AND external_id=?",
            (provider, external_id),
        ).fetchone()
        if not row:
            return None
        if row["status"] == "earned":
            return _reverse_earned_locked(db, row, provider, external_id, now)
        if row["status"] == "pending":
            changed = db.execute(
                """UPDATE referral_rewards
                   SET status='cancelled',updated_at=?,cancelled_at=?
                   WHERE provider=? AND external_id=? AND status='pending'""",
                (now, now, provider, external_id),
            )
            if changed.rowcount != 1:
                raise RuntimeError("État de parrainage incohérent")
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
        # Serialize the read-check-write sequence across processes. SQLite
        # otherwise allows concurrent callers to observe the same balance
        # before either debit is committed.
        db.execute("BEGIN IMMEDIATE")
        account = _account_by_code(db, code)
        if not account:
            raise ValueError("Code de parrainage inconnu")
        balance = _wallet_balance_locked(db, account["id"])
        if amount > balance:
            raise ValueError("Solde de cagnotte insuffisant")
        tombstone = db.execute(
            """SELECT 1 FROM referral_redeem_tombstone
               WHERE account_id=? AND reference_hash=?""",
            (account["id"], _reference_hash(reference)),
        ).fetchone()
        if tombstone:
            raise ValueError("Cette utilisation de cagnotte a déjà été enregistrée")
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
        checkpoint = db.execute(
            """SELECT balance_cents,compacted_entries,updated_at
               FROM referral_ledger_checkpoint WHERE account_id=?""",
            (account["id"],),
        ).fetchone()
        balance = _wallet_balance_locked(db, account["id"])
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
            "compactedBalanceCents": int(checkpoint["balance_cents"]) if checkpoint else 0,
            "compactedEntries": int(checkpoint["compacted_entries"]) if checkpoint else 0,
            "compactedAt": str(checkpoint["updated_at"]) if checkpoint else "",
            "pendingCents": pending_cents,
            "earnedReferrals": counts.get("earned", 0),
            "pendingReferrals": counts.get("pending", 0),
            "cancelledReferrals": counts.get("cancelled", 0),
            "reversedReferrals": counts.get("reversed", 0),
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


def _canonical_reward_for_reference_locked(
    db,
    account_id: str,
    reference: str,
) -> tuple[str, int, str] | None:
    rewards = db.execute(
        """SELECT provider,external_id,reward_cents,status
           FROM referral_rewards
           WHERE account_id=? AND status IN ('earned','reversed')""",
        (account_id,),
    ).fetchall()
    modern = [
        row for row in rewards
        if _reward_ledger_reference(row["provider"], row["external_id"]) == reference
    ]
    if len(modern) == 1:
        row = modern[0]
        return (
            _reward_ledger_reference(row["provider"], row["external_id"]),
            int(row["reward_cents"]),
            str(row["status"]),
        )
    legacy = [
        row for row in rewards
        if _legacy_reward_ledger_reference(row["provider"], row["external_id"]) == reference
    ]
    if len(legacy) == 1:
        row = legacy[0]
        return (
            _reward_ledger_reference(row["provider"], row["external_id"]),
            int(row["reward_cents"]),
            str(row["status"]),
        )
    if modern or legacy:
        raise RuntimeError("Référence historique de parrainage ambiguë")
    return None


def _upsert_compacted_reward_locked(
    db,
    account_id: str,
    reference: str,
    amount_cents: int,
    reversed_state: bool,
    stamp: str,
) -> None:
    existing = db.execute(
        """SELECT amount_cents,reversed FROM referral_compacted_reward_evidence
           WHERE account_id=? AND reference=?""",
        (account_id, reference),
    ).fetchone()
    if existing and int(existing["amount_cents"]) != int(amount_cents):
        raise RuntimeError("Intégrité du crédit compacté incohérente")
    reversed_value = bool(reversed_state) or bool(existing and existing["reversed"])
    material = (
        f"{account_id}|{reference}|{int(amount_cents)}|{int(reversed_value)}"
    )
    evidence_hash = hashlib.sha256(material.encode("utf-8")).hexdigest()
    db.execute(
        """INSERT INTO referral_compacted_reward_evidence(
             account_id,reference,amount_cents,reversed,compacted_at,evidence_hash
           ) VALUES(?,?,?,?,?,?)
           ON CONFLICT(account_id,reference) DO UPDATE SET
             amount_cents=excluded.amount_cents,
             reversed=MAX(referral_compacted_reward_evidence.reversed,excluded.reversed),
             compacted_at=excluded.compacted_at,
             evidence_hash=excluded.evidence_hash""",
        (
            account_id, reference, int(amount_cents), int(reversed_value),
            stamp, evidence_hash,
        ),
    )


def compact_ledger(
    retention_days: int,
    *,
    now: datetime.datetime | None = None,
    dry_run: bool = False,
) -> dict:
    days = int(retention_days)
    if days < 1 or days > 36500:
        raise ValueError("Durée de compaction invalide")
    current = now or datetime.datetime.now(datetime.timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=datetime.timezone.utc)
    cutoff = (current - datetime.timedelta(days=days)).isoformat(timespec="seconds")
    stamp = current.isoformat(timespec="seconds")
    init_db()
    with analytics.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        rows = db.execute(
            """SELECT id,account_id,kind,amount_cents,reference,created_at
               FROM referral_ledger WHERE created_at<?
               ORDER BY id""",
            (cutoff,),
        ).fetchall()
        eligible: list[dict] = []
        skipped = 0
        for row in rows:
            item = dict(row)
            kind = str(item["kind"])
            if kind in {"earn", "reverse"}:
                reward = _canonical_reward_for_reference_locked(
                    db, str(item["account_id"]), str(item["reference"])
                )
                if reward is None:
                    skipped += 1
                    continue
                canonical, reward_cents, reward_status = reward
                expected = reward_cents if kind == "earn" else -reward_cents
                if int(item["amount_cents"]) != expected:
                    raise RuntimeError("Montant historique de parrainage incohérent")
                item["canonical_reference"] = canonical
                item["reward_cents"] = reward_cents
                item["reward_reversed"] = reward_status == "reversed" or kind == "reverse"
                eligible.append(item)
            elif kind == "redeem":
                eligible.append(item)
            else:
                skipped += 1

        net_by_account: dict[str, int] = {}
        count_by_account: dict[str, int] = {}
        if not dry_run:
            for item in eligible:
                account_id = str(item["account_id"])
                kind = str(item["kind"])
                if kind in {"earn", "reverse"}:
                    _upsert_compacted_reward_locked(
                        db,
                        account_id,
                        str(item["canonical_reference"]),
                        int(item["reward_cents"]),
                        bool(item["reward_reversed"]),
                        stamp,
                    )
                else:
                    reference_hash = _reference_hash(str(item["reference"]))
                    material = (
                        f"{account_id}|redeem|{reference_hash}|{int(item['amount_cents'])}"
                    )
                    evidence_hash = hashlib.sha256(material.encode("utf-8")).hexdigest()
                    existing = db.execute(
                        """SELECT amount_cents FROM referral_redeem_tombstone
                           WHERE account_id=? AND reference_hash=?""",
                        (account_id, reference_hash),
                    ).fetchone()
                    if existing and int(existing["amount_cents"]) != int(item["amount_cents"]):
                        raise RuntimeError("Intégrité du redemption compacté incohérente")
                    db.execute(
                        """INSERT INTO referral_redeem_tombstone(
                             account_id,reference_hash,amount_cents,compacted_at,evidence_hash
                           ) VALUES(?,?,?,?,?)
                           ON CONFLICT(account_id,reference_hash) DO UPDATE SET
                             compacted_at=excluded.compacted_at,
                             evidence_hash=excluded.evidence_hash""",
                        (
                            account_id, reference_hash, int(item["amount_cents"]),
                            stamp, evidence_hash,
                        ),
                    )
                net_by_account[account_id] = (
                    net_by_account.get(account_id, 0) + int(item["amount_cents"])
                )
                count_by_account[account_id] = count_by_account.get(account_id, 0) + 1

            for account_id, net in net_by_account.items():
                count = count_by_account[account_id]
                previous = db.execute(
                    """SELECT balance_cents,compacted_entries
                       FROM referral_ledger_checkpoint WHERE account_id=?""",
                    (account_id,),
                ).fetchone()
                balance = (int(previous["balance_cents"]) if previous else 0) + net
                entries = (int(previous["compacted_entries"]) if previous else 0) + count
                material = f"{account_id}|{balance}|{entries}|{stamp}"
                evidence_hash = hashlib.sha256(material.encode("utf-8")).hexdigest()
                db.execute(
                    """INSERT INTO referral_ledger_checkpoint(
                         account_id,balance_cents,compacted_entries,updated_at,evidence_hash
                       ) VALUES(?,?,?,?,?)
                       ON CONFLICT(account_id) DO UPDATE SET
                         balance_cents=excluded.balance_cents,
                         compacted_entries=excluded.compacted_entries,
                         updated_at=excluded.updated_at,
                         evidence_hash=excluded.evidence_hash""",
                    (account_id, balance, entries, stamp, evidence_hash),
                )
            if eligible:
                placeholders = ",".join("?" for _ in eligible)
                db.execute(
                    f"DELETE FROM referral_ledger WHERE id IN ({placeholders})",
                    tuple(int(item["id"]) for item in eligible),
                )

        net = sum(int(item["amount_cents"]) for item in eligible)
        evidence = hashlib.sha256(
            json.dumps(
                {
                    "cutoff": cutoff,
                    "eligibleCount": len(eligible),
                    "skippedCount": skipped,
                    "netCents": net,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return {
            "ok": True,
            "dryRun": bool(dry_run),
            "cutoffAt": cutoff,
            "compactedEntries": len(eligible),
            "skippedEntries": skipped,
            "netCents": net,
            "evidenceHash": evidence,
        }


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
