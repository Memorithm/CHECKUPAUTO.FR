from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from pathlib import Path

import compliance_store
import data_subject_rights


ADAPTER = "referral_wallet"
INITIAL_ACTION = "deactivate_retained_erasure"
COMPLETE_ACTION = "erasure_complete"


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _digest(value: object, name: str) -> str:
    raw = str(value or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", raw):
        raise ValueError(f"{name} invalide")
    return raw


def _ensure_schema(db: sqlite3.Connection) -> None:
    # Use individual execute() calls rather than executescript(): sqlite3 may
    # implicitly commit a pending transaction before executescript(), which would
    # split final-purge audit state from the DSAR completion proof.
    db.execute(
        """CREATE TABLE IF NOT EXISTS referral_wallet_erasure_completion_link(
             request_id TEXT PRIMARY KEY,
             account_hash TEXT NOT NULL UNIQUE,
             created_at TEXT NOT NULL
           )"""
    )
    db.execute(
        """CREATE INDEX IF NOT EXISTS idx_referral_erasure_completion_account
           ON referral_wallet_erasure_completion_link(account_hash)"""
    )


def stage(
    request_id: object,
    account_id: object,
    db_path: Path | str | None = None,
) -> dict:
    """Persist only the hashed wallet linkage needed to prove deferred erasure.

    The call is made after ownership/retention preconditions are proven and before
    the analytics mutation. That closes the crash gap where a wallet could be
    irreversibly retired without retaining enough non-raw evidence to associate
    its later retention-expiry purge with the original DSAR.
    """
    rid = data_subject_rights._request_id(request_id)
    account = str(account_id or "").strip().lower()
    try:
        parsed = uuid.UUID(account)
    except (ValueError, AttributeError) as exc:
        raise ValueError("accountId invalide") from exc
    if str(parsed) != account:
        raise ValueError("accountId invalide")
    account_hash = _hash(account)

    data_subject_rights._init_audit(db_path)
    with compliance_store.connect(db_path) as db:
        _ensure_schema(db)
        row = db.execute(
            "SELECT request_type,status FROM rights_requests WHERE request_id=?",
            (rid,),
        ).fetchone()
        if not row or str(row["request_type"]) != "erasure":
            raise RuntimeError("demande d'effacement de cagnotte invalide")
        if str(row["status"]) not in {"open", "in_progress"}:
            raise RuntimeError("demande non exécutable")
        existing = db.execute(
            "SELECT request_id,account_hash FROM referral_wallet_erasure_completion_link WHERE request_id=? OR account_hash=?",
            (rid, account_hash),
        ).fetchall()
        for item in existing:
            if str(item["request_id"]) != rid or str(item["account_hash"]) != account_hash:
                raise RuntimeError("preuve d'effacement différé déjà liée à une autre demande")
        db.execute(
            """INSERT OR IGNORE INTO referral_wallet_erasure_completion_link(
                 request_id,account_hash,created_at
               ) VALUES(?,?,?)""",
            (rid, account_hash, data_subject_rights._now_iso()),
        )
    return {
        "ok": True,
        "requestId": rid,
        "accountHash": account_hash,
        "rawAccountIdentifierPersisted": False,
    }


def complete_in_transaction(
    db: sqlite3.Connection,
    account_hash: object,
    purge_evidence_hash: object,
    *,
    stamp: str | None = None,
) -> dict:
    """Append ``erasure_complete`` when final physical purge is proven.

    This function deliberately accepts an existing compliance transaction so the
    final-purge audit transition and the DSAR completion evidence commit together.
    Missing initial execution evidence never blocks physical minimisation: the
    hashed link is retained and the DSAR remains incomplete instead.
    """
    account_digest = _digest(account_hash, "accountHash")
    purge_digest = _digest(purge_evidence_hash, "purgeEvidenceHash")
    _ensure_schema(db)
    link = db.execute(
        """SELECT request_id FROM referral_wallet_erasure_completion_link
           WHERE account_hash=?""",
        (account_digest,),
    ).fetchone()
    if not link:
        return {"linked": False, "completed": False, "reason": "no_dsar_link"}

    rid = str(link["request_id"])
    request = db.execute(
        "SELECT request_type,status FROM rights_requests WHERE request_id=?",
        (rid,),
    ).fetchone()
    if not request:
        db.execute(
            "DELETE FROM referral_wallet_erasure_completion_link WHERE account_hash=?",
            (account_digest,),
        )
        return {"linked": True, "completed": False, "reason": "request_missing"}
    if str(request["request_type"]) != "erasure":
        return {"linked": True, "completed": False, "reason": "request_type_mismatch"}
    if str(request["status"]) in {"closed", "rejected"}:
        db.execute(
            "DELETE FROM referral_wallet_erasure_completion_link WHERE account_hash=?",
            (account_digest,),
        )
        return {"linked": True, "completed": False, "reason": "request_terminal"}

    complete = db.execute(
        """SELECT 1 FROM rights_execution_audit
           WHERE request_id=? AND adapter=? AND action=? LIMIT 1""",
        (rid, ADAPTER, COMPLETE_ACTION),
    ).fetchone()
    if complete:
        db.execute(
            "DELETE FROM referral_wallet_erasure_completion_link WHERE account_hash=?",
            (account_digest,),
        )
        return {"linked": True, "completed": True, "reason": "already_complete"}

    initial = db.execute(
        """SELECT 1 FROM rights_execution_audit
           WHERE request_id=? AND adapter=? AND action=? LIMIT 1""",
        (rid, ADAPTER, INITIAL_ACTION),
    ).fetchone()
    if not initial:
        return {"linked": True, "completed": False, "reason": "initial_execution_missing"}

    material = {
        "requestId": rid,
        "adapter": ADAPTER,
        "action": COMPLETE_ACTION,
        "accountHash": account_digest,
        "purgeEvidenceHash": purge_digest,
        "rawAccountIdentifierPersisted": False,
    }
    evidence_hash = _hash(
        json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    )
    created_at = str(stamp or data_subject_rights._now_iso())
    db.execute(
        """INSERT INTO rights_execution_audit(
             execution_id,request_id,request_type,adapter,action,evidence_hash,created_at
           ) VALUES(?,?,?,?,?,?,?)""",
        (
            uuid.uuid4().hex,
            rid,
            "erasure",
            ADAPTER,
            COMPLETE_ACTION,
            evidence_hash,
            created_at,
        ),
    )
    db.execute(
        "UPDATE rights_requests SET status='in_progress',closed_at='' WHERE request_id=?",
        (rid,),
    )
    db.execute(
        "DELETE FROM referral_wallet_erasure_completion_link WHERE account_hash=?",
        (account_digest,),
    )
    return {
        "linked": True,
        "completed": True,
        "reason": "completed",
        "requestId": rid,
        "evidenceHash": evidence_hash,
    }


def pending_count(db_path: Path | str | None = None) -> int:
    compliance_store.init_db(db_path)
    with compliance_store.connect(db_path) as db:
        _ensure_schema(db)
        return int(
            db.execute(
                "SELECT COUNT(*) n FROM referral_wallet_erasure_completion_link"
            ).fetchone()["n"]
        )
