from __future__ import annotations

import hashlib
import hmac
import json
import re
import sqlite3
import uuid
from pathlib import Path

import analytics_store as analytics
import compliance_store
import data_subject_rights
import referral_engine
import referral_wallet_claims


ADAPTER = "referral_wallet"
PAGE_SIZE = 200
_INITIAL_ACTION = "export_bounded"
_COMPLETE_ACTION = "export_complete"
_ZERO_CHAIN = "0" * 64


def _account_id(value: object) -> str:
    raw = str(value or "").strip().lower()
    try:
        parsed = uuid.UUID(raw)
    except (ValueError, AttributeError) as exc:
        raise ValueError("accountId invalide") from exc
    if str(parsed) != raw:
        raise ValueError("accountId invalide")
    return raw


def _session_id(value: object) -> str:
    raw = str(value or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{32}", raw):
        raise ValueError("sessionId invalide")
    return raw


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _public_ledger_row(row: sqlite3.Row) -> dict:
    return {
        "kind": str(row["kind"]),
        "amountCents": int(row["amount_cents"]),
        "referenceHash": _hash(str(row["reference"])),
        "createdAt": str(row["created_at"]),
    }


def _chain_step(previous: str, row: sqlite3.Row) -> str:
    material = {
        "id": int(row["id"]),
        "kind": str(row["kind"]),
        "amountCents": int(row["amount_cents"]),
        "referenceHash": _hash(str(row["reference"])),
        "createdAt": str(row["created_at"]),
    }
    canonical = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return _hash(previous + "|" + canonical)


def _chain_rows(rows: list[sqlite3.Row], previous: str = _ZERO_CHAIN) -> str:
    digest = previous
    for row in rows:
        digest = _chain_step(digest, row)
    return digest


def _page_hash(rows: list[sqlite3.Row]) -> str:
    public = [_public_ledger_row(row) for row in rows]
    return _hash(json.dumps(public, sort_keys=True, separators=(",", ":"), ensure_ascii=False))


def _ensure_schema(db: sqlite3.Connection) -> None:
    # Keep paged state in the compliance database. Raw account/install identifiers
    # are deliberately excluded: the account is linked only through SHA-256.
    db.execute(
        """CREATE TABLE IF NOT EXISTS referral_wallet_export_session(
             session_id TEXT PRIMARY KEY,
             request_id TEXT NOT NULL UNIQUE,
             request_type TEXT NOT NULL,
             account_hash TEXT NOT NULL,
             ledger_max_id INTEGER NOT NULL,
             expected_count INTEGER NOT NULL,
             next_created_at TEXT NOT NULL,
             next_id INTEGER NOT NULL,
             rows_seen INTEGER NOT NULL,
             chain_hash TEXT NOT NULL,
             created_at TEXT NOT NULL,
             updated_at TEXT NOT NULL,
             completed_at TEXT NOT NULL DEFAULT '',
             invalidated_at TEXT NOT NULL DEFAULT '',
             invalid_reason TEXT NOT NULL DEFAULT '',
             completion_evidence_hash TEXT NOT NULL DEFAULT ''
           )"""
    )
    db.execute(
        """CREATE INDEX IF NOT EXISTS idx_referral_wallet_export_request
           ON referral_wallet_export_session(request_id,completed_at,invalidated_at)"""
    )


def _request_context(
    request_id: object,
    installation_id: object,
    account_id: object,
    db_path: Path | str | None = None,
) -> tuple[str, str, str, sqlite3.Row]:
    rid = data_subject_rights._request_id(request_id)
    installation = data_subject_rights._mobile_installation(installation_id)
    account = _account_id(account_id)
    row = data_subject_rights._request(rid, db_path)
    if str(row["status"]) not in {"open", "in_progress"}:
        raise RuntimeError("demande non exécutable")
    if str(row["request_type"]) not in {"access", "portability"}:
        raise NotImplementedError("export paginé non applicable à ce droit")
    subject_hash = _hash(installation)
    if not hmac.compare_digest(str(row["subject_ref_hash"]), subject_hash):
        raise PermissionError("référence du demandeur refusée")
    if not referral_wallet_claims.ownership_matches(account, installation):
        raise PermissionError("propriété de cagnotte non prouvée")
    return rid, installation, account, row


def _snapshot_state(account: str) -> tuple[dict, list[sqlite3.Row], int]:
    referral_engine.init_db()
    referral_wallet_claims.init_db()
    with analytics.connect() as db:
        db.execute("BEGIN")
        row = db.execute(
            "SELECT id,code,active,reward_cents,currency,created_at FROM referral_accounts WHERE id=?",
            (account,),
        ).fetchone()
        if not row:
            raise LookupError("cagnotte inconnue")
        reward_rows = db.execute(
            """SELECT status,COUNT(*) n,COALESCE(SUM(reward_cents),0) cents
               FROM referral_rewards WHERE account_id=? GROUP BY status ORDER BY status""",
            (account,),
        ).fetchall()
        pending_cents = int(
            db.execute(
                """SELECT COALESCE(SUM(reward_cents),0) total
                   FROM referral_rewards WHERE account_id=? AND status='pending'""",
                (account,),
            ).fetchone()["total"]
        )
        boundary = db.execute(
            "SELECT COALESCE(MAX(id),0) max_id,COUNT(*) n FROM referral_ledger WHERE account_id=?",
            (account,),
        ).fetchone()
        max_id = int(boundary["max_id"])
        total_ledger = int(boundary["n"])
        ledger = db.execute(
            """SELECT id,kind,amount_cents,reference,created_at
               FROM referral_ledger
               WHERE account_id=? AND id<=?
               ORDER BY created_at DESC,id DESC LIMIT ?""",
            (account, max_id, PAGE_SIZE),
        ).fetchall()
        balance_cents = referral_engine._wallet_balance_locked(db, account)

    data = {
        "account": {
            "accountId": str(row["id"]),
            "referralCode": str(row["code"]),
            "active": bool(row["active"]),
            "currency": str(row["currency"]),
            "rewardCents": int(row["reward_cents"]),
            "createdAt": str(row["created_at"]),
        },
        "wallet": {
            "balanceCents": balance_cents,
            "pendingCents": pending_cents,
        },
        "rewards": [
            {
                "status": str(item["status"]),
                "count": int(item["n"]),
                "rewardCents": int(item["cents"]),
            }
            for item in reward_rows
        ],
        "ledger": [_public_ledger_row(item) for item in ledger],
        "ledgerCount": total_ledger,
        "ledgerTruncated": total_ledger > len(ledger),
        "thirdPartyAppointmentIdentifiersExposed": False,
    }
    return data, ledger, max_id


def snapshot(account_id: object) -> dict:
    account = _account_id(account_id)
    data, _, _ = _snapshot_state(account)
    return data


def begin(
    request_id: object,
    installation_id: object,
    account_id: object,
    db_path: Path | str | None = None,
) -> dict:
    """Return a bounded wallet snapshot and stage a stable session when needed.

    The stable boundary is the highest ledger row id visible in the same SQLite
    read transaction as page 1. Later inserts cannot enter the export. Deletion,
    compaction or mutation inside the boundary is detected before completion by
    recomputing the complete chain.
    """
    rid, _, account, row = _request_context(
        request_id, installation_id, account_id, db_path
    )
    data, raw_page, max_id = _snapshot_state(account)
    if not data["ledgerTruncated"]:
        return {
            "data": data,
            "exportComplete": True,
            "pagedExport": None,
        }

    session = uuid.uuid4().hex
    stamp = data_subject_rights._now_iso()
    chain = _chain_rows(raw_page)
    last = raw_page[-1]
    account_hash = _hash(account)
    data_subject_rights._init_audit(db_path)
    with compliance_store.connect(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        _ensure_schema(db)
        existing = db.execute(
            "SELECT session_id FROM referral_wallet_export_session WHERE request_id=?",
            (rid,),
        ).fetchone()
        if existing:
            raise RuntimeError("session d'export paginé déjà existante")
        db.execute(
            """INSERT INTO referral_wallet_export_session(
                 session_id,request_id,request_type,account_hash,ledger_max_id,
                 expected_count,next_created_at,next_id,rows_seen,chain_hash,
                 created_at,updated_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                session,
                rid,
                str(row["request_type"]),
                account_hash,
                max_id,
                int(data["ledgerCount"]),
                str(last["created_at"]),
                int(last["id"]),
                len(raw_page),
                chain,
                stamp,
                stamp,
            ),
        )

    return {
        "data": data,
        "exportComplete": False,
        "pagedExport": {
            "sessionId": session,
            "pageSize": PAGE_SIZE,
            "pageNumber": 1,
            "rowsExported": len(raw_page),
            "expectedLedgerCount": int(data["ledgerCount"]),
            "hasMore": True,
            "pageHash": _page_hash(raw_page),
            "snapshotChainHash": chain,
            "stableBoundary": True,
            "newLedgerRowsAfterStartExcluded": True,
            "rawAccountIdentifierPersisted": False,
        },
    }


def _mark_invalid(
    db: sqlite3.Connection,
    session_id: str,
    reason: str,
    stamp: str,
) -> None:
    db.execute(
        """UPDATE referral_wallet_export_session
           SET invalidated_at=?,invalid_reason=?,updated_at=?
           WHERE session_id=? AND completed_at='' AND invalidated_at=''""",
        (stamp, reason, stamp, session_id),
    )


def continue_export(
    request_id: object,
    installation_id: object,
    account_id: object,
    session_id: object,
    db_path: Path | str | None = None,
) -> dict:
    rid, _, account, row = _request_context(
        request_id, installation_id, account_id, db_path
    )
    sid = _session_id(session_id)
    account_hash = _hash(account)
    stamp = data_subject_rights._now_iso()
    data_subject_rights._init_audit(db_path)

    with compliance_store.connect(db_path) as compliance:
        compliance.execute("BEGIN IMMEDIATE")
        _ensure_schema(compliance)
        session = compliance.execute(
            """SELECT * FROM referral_wallet_export_session
               WHERE session_id=? AND request_id=?""",
            (sid, rid),
        ).fetchone()
        if not session:
            raise LookupError("session d'export inconnue")
        if not hmac.compare_digest(str(session["account_hash"]), account_hash):
            raise PermissionError("cagnotte de session refusée")
        if str(session["request_type"]) != str(row["request_type"]):
            raise RuntimeError("type de demande de session incohérent")
        if str(session["completed_at"]):
            return {
                "ok": True,
                "requestId": rid,
                "requestType": str(row["request_type"]),
                "adapter": ADAPTER,
                "format": "application/json",
                "data": {"ledger": []},
                "pagedExport": {
                    "sessionId": sid,
                    "rowsExported": 0,
                    "hasMore": False,
                    "exportComplete": True,
                    "alreadyComplete": True,
                    "completionEvidenceHash": str(session["completion_evidence_hash"]),
                },
                "requestStatus": "in_progress",
                "requestComplete": False,
            }
        if str(session["invalidated_at"]):
            return {
                "ok": True,
                "requestId": rid,
                "requestType": str(row["request_type"]),
                "adapter": ADAPTER,
                "format": "application/json",
                "data": {"ledger": []},
                "pagedExport": {
                    "sessionId": sid,
                    "rowsExported": 0,
                    "hasMore": False,
                    "exportComplete": False,
                    "invalidated": True,
                    "invalidReason": str(session["invalid_reason"]),
                },
                "requestStatus": "in_progress",
                "requestComplete": False,
            }

        expected = int(session["expected_count"])
        seen = int(session["rows_seen"])
        max_id = int(session["ledger_max_id"])
        next_created = str(session["next_created_at"])
        next_id = int(session["next_id"])

        with analytics.connect() as analytics_db:
            analytics_db.execute("BEGIN")
            page = analytics_db.execute(
                """SELECT id,kind,amount_cents,reference,created_at
                   FROM referral_ledger
                   WHERE account_id=? AND id<=?
                     AND (created_at<? OR (created_at=? AND id<?))
                   ORDER BY created_at DESC,id DESC LIMIT ?""",
                (
                    account,
                    max_id,
                    next_created,
                    next_created,
                    next_id,
                    PAGE_SIZE,
                ),
            ).fetchall()

            new_seen = seen + len(page)
            if not page or new_seen > expected:
                _mark_invalid(compliance, sid, "snapshot_boundary_changed", stamp)
                return {
                    "ok": True,
                    "requestId": rid,
                    "requestType": str(row["request_type"]),
                    "adapter": ADAPTER,
                    "format": "application/json",
                    "data": {"ledger": []},
                    "pagedExport": {
                        "sessionId": sid,
                        "rowsExported": 0,
                        "hasMore": False,
                        "exportComplete": False,
                        "invalidated": True,
                        "invalidReason": "snapshot_boundary_changed",
                    },
                    "requestStatus": "in_progress",
                    "requestComplete": False,
                }

            chain = _chain_rows(page, str(session["chain_hash"]))
            has_more = new_seen < expected
            verification_count = -1
            verification_chain = ""
            if not has_more:
                all_rows = analytics_db.execute(
                    """SELECT id,kind,amount_cents,reference,created_at
                       FROM referral_ledger
                       WHERE account_id=? AND id<=?
                       ORDER BY created_at DESC,id DESC""",
                    (account, max_id),
                ).fetchall()
                verification_count = len(all_rows)
                verification_chain = _chain_rows(all_rows)

        if not has_more and (
            verification_count != expected or verification_chain != chain
        ):
            _mark_invalid(compliance, sid, "snapshot_boundary_changed", stamp)
            return {
                "ok": True,
                "requestId": rid,
                "requestType": str(row["request_type"]),
                "adapter": ADAPTER,
                "format": "application/json",
                "data": {"ledger": []},
                "pagedExport": {
                    "sessionId": sid,
                    "rowsExported": 0,
                    "hasMore": False,
                    "exportComplete": False,
                    "invalidated": True,
                    "invalidReason": "snapshot_boundary_changed",
                },
                "requestStatus": "in_progress",
                "requestComplete": False,
            }

        if has_more:
            last = page[-1]
            compliance.execute(
                """UPDATE referral_wallet_export_session
                   SET next_created_at=?,next_id=?,rows_seen=?,chain_hash=?,updated_at=?
                   WHERE session_id=? AND completed_at='' AND invalidated_at=''""",
                (
                    str(last["created_at"]),
                    int(last["id"]),
                    new_seen,
                    chain,
                    stamp,
                    sid,
                ),
            )
            completion_hash = ""
            execution_id = ""
        else:
            initial = compliance.execute(
                """SELECT 1 FROM rights_execution_audit
                   WHERE request_id=? AND request_type=? AND adapter=? AND action=?
                   LIMIT 1""",
                (rid, str(row["request_type"]), ADAPTER, _INITIAL_ACTION),
            ).fetchone()
            if not initial:
                raise RuntimeError("preuve initiale d'export borné absente")
            existing_complete = compliance.execute(
                """SELECT execution_id,evidence_hash FROM rights_execution_audit
                   WHERE request_id=? AND request_type=? AND adapter=? AND action=?
                   LIMIT 1""",
                (rid, str(row["request_type"]), ADAPTER, _COMPLETE_ACTION),
            ).fetchone()
            if existing_complete:
                execution_id = str(existing_complete["execution_id"])
                completion_hash = str(existing_complete["evidence_hash"])
            else:
                evidence = {
                    "requestId": rid,
                    "requestType": str(row["request_type"]),
                    "adapter": ADAPTER,
                    "action": _COMPLETE_ACTION,
                    "sessionIdHash": _hash(sid),
                    "accountHash": account_hash,
                    "expectedLedgerCount": expected,
                    "rowsExported": new_seen,
                    "ledgerBoundaryMaxId": max_id,
                    "snapshotChainHash": chain,
                    "pageSize": PAGE_SIZE,
                    "rawAccountIdentifierPersisted": False,
                    "thirdPartyAppointmentIdentifiersExposed": False,
                }
                completion_hash = _hash(
                    json.dumps(
                        evidence,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                    )
                )
                execution_id = uuid.uuid4().hex
                compliance.execute(
                    """INSERT INTO rights_execution_audit(
                         execution_id,request_id,request_type,adapter,action,
                         evidence_hash,created_at
                       ) VALUES(?,?,?,?,?,?,?)""",
                    (
                        execution_id,
                        rid,
                        str(row["request_type"]),
                        ADAPTER,
                        _COMPLETE_ACTION,
                        completion_hash,
                        stamp,
                    ),
                )
                compliance.execute(
                    """UPDATE rights_requests
                       SET status='in_progress',closed_at='' WHERE request_id=?""",
                    (rid,),
                )
            compliance.execute(
                """UPDATE referral_wallet_export_session
                   SET rows_seen=?,chain_hash=?,updated_at=?,completed_at=?,
                       completion_evidence_hash=?
                   WHERE session_id=? AND completed_at='' AND invalidated_at=''""",
                (new_seen, chain, stamp, stamp, completion_hash, sid),
            )

        return {
            "ok": True,
            "requestId": rid,
            "requestType": str(row["request_type"]),
            "adapter": ADAPTER,
            "format": "application/json",
            "data": {"ledger": [_public_ledger_row(item) for item in page]},
            "pagedExport": {
                "sessionId": sid,
                "pageSize": PAGE_SIZE,
                "rowsExported": len(page),
                "rowsExportedTotal": new_seen,
                "expectedLedgerCount": expected,
                "hasMore": has_more,
                "exportComplete": not has_more,
                "invalidated": False,
                "pageHash": _page_hash(page),
                "snapshotChainHash": chain,
                "completionEvidenceHash": completion_hash,
                "executionId": execution_id,
                "stableBoundary": True,
                "newLedgerRowsAfterStartExcluded": True,
                "rawAccountIdentifierPersisted": False,
            },
            "requestStatus": "in_progress",
            "requestComplete": False,
        }


def capability(db_path: Path | str | None = None) -> dict:
    compliance_store.init_db(db_path)
    with compliance_store.connect(db_path) as db:
        _ensure_schema(db)
        active = int(
            db.execute(
                """SELECT COUNT(*) n FROM referral_wallet_export_session
                   WHERE completed_at='' AND invalidated_at=''"""
            ).fetchone()["n"]
        )
        completed = int(
            db.execute(
                """SELECT COUNT(*) n FROM referral_wallet_export_session
                   WHERE completed_at<>''"""
            ).fetchone()["n"]
        )
        invalidated = int(
            db.execute(
                """SELECT COUNT(*) n FROM referral_wallet_export_session
                   WHERE invalidated_at<>''"""
            ).fetchone()["n"]
        )
    return {
        "pagedExportReady": True,
        "pageSize": PAGE_SIZE,
        "stableBoundary": True,
        "newRowsAfterStartExcluded": True,
        "mutationOrCompactionDetectedBeforeCompletion": True,
        "perPageHash": True,
        "rollingSnapshotChainHash": True,
        "rawAccountIdentifierPersisted": False,
        "activeSessionCount": active,
        "completedSessionCount": completed,
        "invalidatedSessionCount": invalidated,
    }
