from __future__ import annotations

import hashlib
import hmac
from pathlib import Path

import analytics_store as analytics
import compliance_store
import data_subject_rights
import referral_engine
import referral_wallet_claims
import retention_enforcement


RETENTION_RULE_ID = "referral_ledger"


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _retention_state(db_path: Path | str | None = None) -> dict:
    state = retention_enforcement.policy(RETENTION_RULE_ID, db_path)
    ready = bool(state.get("ready")) and bool(state.get("legalReviewConfirmed"))
    return {
        "ruleId": RETENTION_RULE_ID,
        "ready": ready,
        "activeDays": int(state["activeDays"]) if ready else None,
        "legalReviewConfirmed": bool(state.get("legalReviewConfirmed")),
        "blocker": "" if ready else str(state.get("blocker") or "legal_review_required"),
    }


def _init_checkpoint(db_path: Path | str | None = None) -> None:
    data_subject_rights._init_audit(db_path)
    with compliance_store.connect(db_path) as db:
        db.execute(
            """CREATE TABLE IF NOT EXISTS referral_wallet_erasure_checkpoint(
                 request_id TEXT PRIMARY KEY,
                 account_hash TEXT NOT NULL,
                 subject_hash TEXT NOT NULL,
                 created_at TEXT NOT NULL
               )"""
        )


def _checkpoint_matches(
    request_id: str,
    account_id: str,
    installation_id: str,
    db_path: Path | str | None = None,
) -> bool:
    _init_checkpoint(db_path)
    with compliance_store.connect(db_path) as db:
        row = db.execute(
            """SELECT account_hash,subject_hash
               FROM referral_wallet_erasure_checkpoint WHERE request_id=?""",
            (request_id,),
        ).fetchone()
    if not row:
        return False
    return hmac.compare_digest(str(row["account_hash"]), _hash(account_id)) and hmac.compare_digest(
        str(row["subject_hash"]), _hash(installation_id)
    )


def _ensure_checkpoint(
    request_id: str,
    account_id: str,
    installation_id: str,
    db_path: Path | str | None = None,
) -> bool:
    """Persist only hashed retry evidence after wallet ownership was proven.

    The checkpoint closes the cross-database retry gap between the analytics
    mutation and the compliance audit. If the audit write fails after the wallet
    was deactivated, the same verified DSAR can retry without restoring durable
    mobile ownership evidence. No raw installation or wallet identifier is stored.
    """
    if _checkpoint_matches(request_id, account_id, installation_id, db_path):
        return True
    if not referral_wallet_claims.ownership_matches(account_id, installation_id):
        raise PermissionError("propriété de cagnotte non prouvée")
    _init_checkpoint(db_path)
    with compliance_store.connect(db_path) as db:
        db.execute(
            """INSERT INTO referral_wallet_erasure_checkpoint(
                 request_id,account_hash,subject_hash,created_at
               ) VALUES(?,?,?,?)""",
            (
                request_id,
                _hash(account_id),
                _hash(installation_id),
                data_subject_rights._now_iso(),
            ),
        )
    return True


def _clear_checkpoint(request_id: str, db_path: Path | str | None = None) -> None:
    _init_checkpoint(db_path)
    with compliance_store.connect(db_path) as db:
        db.execute(
            "DELETE FROM referral_wallet_erasure_checkpoint WHERE request_id=?",
            (request_id,),
        )


def _retire_account(account_id: str, installation_id: str, checkpoint_verified: bool) -> dict:
    """Disable future referral use while preserving legally retained financial rows.

    Erasure is deliberately refused while the wallet has a non-zero balance or a
    pending reward. That prevents a privacy operation from silently destroying a
    monetary entitlement or debt. Once financially neutral, the shareable code is
    disabled, pending ownership claims are revoked and mobile ownership evidence is
    removed atomically from the analytics database. Ledger/reward history remains
    under the separately configured, legally reviewed retention policy.
    """
    referral_wallet_claims.init_db()
    expected_owner = _hash(installation_id)
    with analytics.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        account = db.execute(
            "SELECT active FROM referral_accounts WHERE id=?",
            (account_id,),
        ).fetchone()
        if not account:
            raise LookupError("cagnotte inconnue")

        owner = db.execute(
            "SELECT installation_hash FROM referral_wallet_owner WHERE account_id=?",
            (account_id,),
        ).fetchone()
        if owner and not hmac.compare_digest(str(owner["installation_hash"]), expected_owner):
            raise PermissionError("propriété de cagnotte non prouvée")
        if not owner and not checkpoint_verified:
            raise PermissionError("propriété de cagnotte non prouvée")

        balance = referral_engine._wallet_balance_locked(db, account_id)
        pending_rewards = int(
            db.execute(
                """SELECT COUNT(*) n FROM referral_rewards
                   WHERE account_id=? AND status='pending'""",
                (account_id,),
            ).fetchone()["n"]
        )
        if balance != 0 or pending_rewards:
            raise RuntimeError("résolution financière de la cagnotte requise avant effacement")

        retained = {
            "rewardRecords": int(
                db.execute(
                    "SELECT COUNT(*) n FROM referral_rewards WHERE account_id=?",
                    (account_id,),
                ).fetchone()["n"]
            ),
            "ledgerRecords": int(
                db.execute(
                    "SELECT COUNT(*) n FROM referral_ledger WHERE account_id=?",
                    (account_id,),
                ).fetchone()["n"]
            ),
            "checkpointRecords": int(
                db.execute(
                    "SELECT COUNT(*) n FROM referral_ledger_checkpoint WHERE account_id=?",
                    (account_id,),
                ).fetchone()["n"]
            ),
            "compactedRewardEvidenceRecords": int(
                db.execute(
                    """SELECT COUNT(*) n FROM referral_compacted_reward_evidence
                       WHERE account_id=?""",
                    (account_id,),
                ).fetchone()["n"]
            ),
            "redeemTombstoneRecords": int(
                db.execute(
                    "SELECT COUNT(*) n FROM referral_redeem_tombstone WHERE account_id=?",
                    (account_id,),
                ).fetchone()["n"]
            ),
        }
        pending_claims = int(
            db.execute(
                "SELECT COUNT(*) n FROM referral_wallet_claim WHERE account_id=?",
                (account_id,),
            ).fetchone()["n"]
        )
        owners = int(
            db.execute(
                "SELECT COUNT(*) n FROM referral_wallet_owner WHERE account_id=?",
                (account_id,),
            ).fetchone()["n"]
        )
        was_active = bool(account["active"])

        db.execute("UPDATE referral_accounts SET active=0 WHERE id=?", (account_id,))
        db.execute("DELETE FROM referral_wallet_claim WHERE account_id=?", (account_id,))
        db.execute("DELETE FROM referral_wallet_owner WHERE account_id=?", (account_id,))

    return {
        "accountDeactivated": was_active,
        "ownershipReleased": owners,
        "pendingClaimsRevoked": pending_claims,
        "balanceCentsAtErasure": 0,
        "pendingRewardsAtErasure": 0,
        "retainedFinancialRecords": retained,
        "financialHistoryRetained": True,
        "thirdPartyAppointmentIdentifiersExposed": False,
    }


def execute(
    request_id: str,
    installation_id: str,
    account_id: str,
    db_path: Path | str | None = None,
) -> dict:
    retention = _retention_state(db_path)
    if not retention["ready"]:
        raise RuntimeError("politique de conservation du ledger non prête")

    checkpoint = _ensure_checkpoint(request_id, account_id, installation_id, db_path)
    result = _retire_account(account_id, installation_id, checkpoint)
    return {**result, "retention": retention}


def finalize(request_id: str, db_path: Path | str | None = None) -> None:
    _clear_checkpoint(request_id, db_path)


def capability(db_path: Path | str | None = None) -> dict:
    retention = _retention_state(db_path)
    return {
        "bound": True,
        "partial": True,
        "retention": retention,
        "zeroBalanceRequired": True,
        "noPendingRewardsRequired": True,
        "ownershipReleasedOnExecution": True,
        "futureReferralUseDisabled": True,
        "financialHistoryRetainedUntilPolicyProcessing": True,
        "rawIdentifiersPersistedByErasureCheckpoint": False,
        "finalPhysicalPurgeComplete": False,
    }
