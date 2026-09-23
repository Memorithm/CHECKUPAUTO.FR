from __future__ import annotations

import datetime
import hashlib
import json
import uuid
from pathlib import Path

import analytics_store as analytics
import compliance_store
import referral_engine
import referral_wallet_claims
import referral_wallet_purge_rights


RULE_ID = "referral_ledger"
_TERMINAL_REWARD_STATUS = ("earned", "cancelled", "reversed")


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _now_iso() -> str:
    return _now().isoformat(timespec="seconds")


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _retired_code(account_id: str) -> str:
    return "erased:" + _hash("referral-wallet-code:" + account_id)


def _cutoff(days: int, now: datetime.datetime | None = None) -> str:
    value = int(days)
    if value < 1 or value > 36500:
        raise ValueError("durée de conservation invalide")
    current = now or _now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=datetime.timezone.utc)
    return (current - datetime.timedelta(days=value)).isoformat(timespec="seconds")


def _init_audit(db_path: Path | str | None = None) -> None:
    compliance_store.init_db(db_path)
    with compliance_store.connect(db_path) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS referral_wallet_final_purge_audit(
              operation_id TEXT PRIMARY KEY,
              account_hash TEXT NOT NULL UNIQUE,
              cutoff_at TEXT NOT NULL,
              planned_rows INTEGER NOT NULL,
              purged_rows INTEGER NOT NULL DEFAULT 0,
              state TEXT NOT NULL,
              evidence_hash TEXT NOT NULL,
              created_at TEXT NOT NULL,
              completed_at TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_referral_final_purge_state
              ON referral_wallet_final_purge_audit(state,created_at);
            """
        )


def _account_hashes() -> set[str]:
    referral_engine.init_db()
    with analytics.connect() as db:
        return {_hash(str(row["id"])) for row in db.execute("SELECT id FROM referral_accounts")}


def _recover_planned(db_path: Path | str | None = None) -> int:
    """Close the cross-database crash gap without storing raw wallet identifiers.

    A planned operation is written before the analytics transaction. If the process
    dies after that transaction committed but before the audit finalization, the
    irreversible absence of the account is recorded as ``recovered_absent`` rather
    than being falsely described as a normally acknowledged completion. Any staged
    DSAR erasure link is completed in the same compliance transaction.
    """
    _init_audit(db_path)
    existing = _account_hashes()
    stamp = _now_iso()
    recovered = 0
    with compliance_store.connect(db_path) as db:
        rows = db.execute(
            """SELECT operation_id,account_hash,planned_rows,evidence_hash
               FROM referral_wallet_final_purge_audit WHERE state='planned'"""
        ).fetchall()
        for row in rows:
            account_hash = str(row["account_hash"])
            if account_hash in existing:
                continue
            purged_rows = max(0, int(row["planned_rows"]))
            evidence = _hash(
                "|".join(
                    (
                        str(row["evidence_hash"]),
                        "recovered_absent",
                        str(purged_rows),
                    )
                )
            )
            db.execute(
                """UPDATE referral_wallet_final_purge_audit
                   SET state='recovered_absent',purged_rows=?,evidence_hash=?,completed_at=?
                   WHERE operation_id=? AND state='planned'""",
                (purged_rows, evidence, stamp, str(row["operation_id"])),
            )
            referral_wallet_purge_rights.complete_in_transaction(
                db,
                account_hash,
                evidence,
                stamp=stamp,
            )
            recovered += 1
    return recovered


def _snapshot_locked(db, account_id: str, cutoff_at: str) -> dict:
    account = db.execute(
        "SELECT id,code,active FROM referral_accounts WHERE id=?",
        (account_id,),
    ).fetchone()
    if not account:
        return {"eligible": False, "reason": "missing", "rowCount": 0}

    owner_count = int(
        db.execute(
            "SELECT COUNT(*) n FROM referral_wallet_owner WHERE account_id=?",
            (account_id,),
        ).fetchone()["n"]
    )
    claim_count = int(
        db.execute(
            "SELECT COUNT(*) n FROM referral_wallet_claim WHERE account_id=?",
            (account_id,),
        ).fetchone()["n"]
    )
    pending = int(
        db.execute(
            """SELECT COUNT(*) n FROM referral_rewards
               WHERE account_id=? AND status='pending'""",
            (account_id,),
        ).fetchone()["n"]
    )
    nonterminal = int(
        db.execute(
            """SELECT COUNT(*) n FROM referral_rewards
               WHERE account_id=? AND status NOT IN ('earned','cancelled','reversed')""",
            (account_id,),
        ).fetchone()["n"]
    )
    recent_rewards = int(
        db.execute(
            """SELECT COUNT(*) n FROM referral_rewards
               WHERE account_id=? AND updated_at>=?""",
            (account_id, cutoff_at),
        ).fetchone()["n"]
    )
    reward_count = int(
        db.execute(
            "SELECT COUNT(*) n FROM referral_rewards WHERE account_id=?",
            (account_id,),
        ).fetchone()["n"]
    )
    ledger_count = int(
        db.execute(
            "SELECT COUNT(*) n FROM referral_ledger WHERE account_id=?",
            (account_id,),
        ).fetchone()["n"]
    )
    checkpoint = db.execute(
        """SELECT balance_cents,updated_at FROM referral_ledger_checkpoint
           WHERE account_id=?""",
        (account_id,),
    ).fetchone()
    checkpoint_recent = bool(checkpoint and str(checkpoint["updated_at"]) >= cutoff_at)
    checkpoint_nonzero = bool(checkpoint and int(checkpoint["balance_cents"]) != 0)
    checkpoint_count = 1 if checkpoint else 0
    compacted_count = int(
        db.execute(
            """SELECT COUNT(*) n FROM referral_compacted_reward_evidence
               WHERE account_id=?""",
            (account_id,),
        ).fetchone()["n"]
    )
    recent_compacted = int(
        db.execute(
            """SELECT COUNT(*) n FROM referral_compacted_reward_evidence
               WHERE account_id=? AND compacted_at>=?""",
            (account_id, cutoff_at),
        ).fetchone()["n"]
    )
    tombstone_count = int(
        db.execute(
            "SELECT COUNT(*) n FROM referral_redeem_tombstone WHERE account_id=?",
            (account_id,),
        ).fetchone()["n"]
    )
    recent_tombstones = int(
        db.execute(
            """SELECT COUNT(*) n FROM referral_redeem_tombstone
               WHERE account_id=? AND compacted_at>=?""",
            (account_id, cutoff_at),
        ).fetchone()["n"]
    )
    balance = referral_engine._wallet_balance_locked(db, account_id)
    canonical_retired = str(account["code"]) == _retired_code(account_id)

    blockers = []
    if bool(account["active"]):
        blockers.append("account_active")
    if not canonical_retired:
        blockers.append("retirement_tombstone_missing")
    if balance != 0:
        blockers.append("non_zero_balance")
    if pending or nonterminal:
        blockers.append("non_terminal_reward")
    if owner_count or claim_count:
        blockers.append("ownership_or_claim_present")
    if ledger_count:
        blockers.append("live_ledger_not_compacted")
    if recent_rewards:
        blockers.append("reward_retention_not_expired")
    if checkpoint_recent or checkpoint_nonzero:
        blockers.append("checkpoint_retention_not_expired")
    if recent_compacted:
        blockers.append("compacted_evidence_retention_not_expired")
    if recent_tombstones:
        blockers.append("redeem_tombstone_retention_not_expired")

    row_count = (
        1
        + reward_count
        + ledger_count
        + checkpoint_count
        + compacted_count
        + tombstone_count
        + owner_count
        + claim_count
    )
    material = {
        "accountHash": _hash(account_id),
        "cutoffAt": cutoff_at,
        "rowCount": row_count,
        "rewardCount": reward_count,
        "checkpointCount": checkpoint_count,
        "compactedEvidenceCount": compacted_count,
        "redeemTombstoneCount": tombstone_count,
        "blockers": sorted(blockers),
    }
    return {
        "eligible": not blockers,
        "reason": "" if not blockers else blockers[0],
        "blockers": blockers,
        "rowCount": row_count,
        "evidenceHash": _hash(json.dumps(material, sort_keys=True, separators=(",", ":"))),
    }


def _candidate_ids(cutoff_at: str) -> list[str]:
    referral_engine.init_db()
    referral_wallet_claims.init_db()
    with analytics.connect() as db:
        rows = db.execute(
            "SELECT id FROM referral_accounts WHERE active=0 AND code LIKE 'erased:%' ORDER BY id"
        ).fetchall()
        result = []
        for row in rows:
            account_id = str(row["id"])
            if _snapshot_locked(db, account_id, cutoff_at)["eligible"]:
                result.append(account_id)
        return result


def _stage(account_id: str, cutoff_at: str, snapshot: dict, db_path: Path | str | None) -> str:
    _init_audit(db_path)
    account_hash = _hash(account_id)
    with compliance_store.connect(db_path) as db:
        existing = db.execute(
            """SELECT operation_id,state FROM referral_wallet_final_purge_audit
               WHERE account_hash=?""",
            (account_hash,),
        ).fetchone()
        if existing:
            state = str(existing["state"])
            if state in {"completed", "recovered_absent"}:
                raise RuntimeError("cagnotte déjà purgée")
            return str(existing["operation_id"])
        operation_id = uuid.uuid4().hex
        db.execute(
            """INSERT INTO referral_wallet_final_purge_audit(
                 operation_id,account_hash,cutoff_at,planned_rows,purged_rows,state,
                 evidence_hash,created_at,completed_at
               ) VALUES(?,?,?,?,0,'planned',?,?, '')""",
            (
                operation_id,
                account_hash,
                cutoff_at,
                int(snapshot["rowCount"]),
                str(snapshot["evidenceHash"]),
                _now_iso(),
            ),
        )
        return operation_id


def _complete(operation_id: str, purged_rows: int, db_path: Path | str | None) -> None:
    stamp = _now_iso()
    with compliance_store.connect(db_path) as db:
        row = db.execute(
            """SELECT account_hash,evidence_hash FROM referral_wallet_final_purge_audit
               WHERE operation_id=? AND state='planned'""",
            (operation_id,),
        ).fetchone()
        if not row:
            raise RuntimeError("preuve de purge planifiée introuvable")
        evidence = _hash(
            "|".join((str(row["evidence_hash"]), "completed", str(int(purged_rows))))
        )
        db.execute(
            """UPDATE referral_wallet_final_purge_audit
               SET state='completed',purged_rows=?,evidence_hash=?,completed_at=?
               WHERE operation_id=? AND state='planned'""",
            (int(purged_rows), evidence, stamp, operation_id),
        )
        referral_wallet_purge_rights.complete_in_transaction(
            db,
            str(row["account_hash"]),
            evidence,
            stamp=stamp,
        )


def _purge_one(account_id: str, cutoff_at: str) -> int:
    with analytics.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        snapshot = _snapshot_locked(db, account_id, cutoff_at)
        if not snapshot["eligible"]:
            raise RuntimeError("cagnotte devenue inéligible à la purge finale")
        removed = 0
        for table in (
            "referral_compacted_reward_evidence",
            "referral_redeem_tombstone",
            "referral_ledger",
            "referral_ledger_checkpoint",
            "referral_rewards",
            "referral_wallet_claim",
            "referral_wallet_owner",
        ):
            removed += int(
                db.execute(f"DELETE FROM {table} WHERE account_id=?", (account_id,)).rowcount or 0
            )
        removed += int(
            db.execute("DELETE FROM referral_accounts WHERE id=?", (account_id,)).rowcount or 0
        )
        if removed != int(snapshot["rowCount"]):
            raise RuntimeError("comptage de purge finale incohérent")
        return removed


def purge_retired_wallets(
    retention_days: int,
    *,
    now: datetime.datetime | None = None,
    dry_run: bool = False,
    db_path: Path | str | None = None,
) -> dict:
    """Physically remove fully expired, retired referral wallets.

    This low-level primitive assumes ``retention_days`` came from the reviewed
    ``referral_ledger`` policy. Call :func:`run_policy` from operator code. No raw
    account id is written to the compliance database or returned to callers.
    """
    cutoff_at = _cutoff(retention_days, now)
    referral_engine.init_db()
    referral_wallet_claims.init_db()
    recovered = 0 if dry_run else _recover_planned(db_path)
    candidates = _candidate_ids(cutoff_at)
    purged_accounts = 0
    purged_rows = 0

    if not dry_run:
        for account_id in candidates:
            with analytics.connect() as db:
                snapshot = _snapshot_locked(db, account_id, cutoff_at)
            if not snapshot["eligible"]:
                continue
            operation_id = _stage(account_id, cutoff_at, snapshot, db_path)
            removed = _purge_one(account_id, cutoff_at)
            purged_accounts += 1
            purged_rows += removed
            _complete(operation_id, removed, db_path)

    material = {
        "cutoffAt": cutoff_at,
        "dryRun": bool(dry_run),
        "eligibleAccounts": len(candidates),
        "purgedAccounts": purged_accounts,
        "purgedRows": purged_rows,
        "recoveredPlannedOperations": recovered,
    }
    return {
        "ok": True,
        **material,
        "evidenceHash": _hash(json.dumps(material, sort_keys=True, separators=(",", ":"))),
        "rawAccountIdentifiersPersisted": False,
    }


def run_policy(
    *,
    dry_run: bool = False,
    db_path: Path | str | None = None,
    now: datetime.datetime | None = None,
) -> dict:
    """Execute only from the configured, legally reviewed referral retention rule."""
    import retention_enforcement

    state = retention_enforcement.policy(RULE_ID, db_path)
    if not bool(state.get("ready")) or not bool(state.get("legalReviewConfirmed")):
        raise RuntimeError("politique de conservation du ledger non prête")
    result = purge_retired_wallets(
        int(state["activeDays"]),
        now=now,
        dry_run=dry_run,
        db_path=db_path,
    )
    return {
        **result,
        "ruleId": RULE_ID,
        "retentionDays": int(state["activeDays"]),
        "legalReviewConfirmed": True,
    }
