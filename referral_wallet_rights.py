from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from pathlib import Path

import analytics_store as analytics
import compliance_store
import data_subject_rights
import referral_engine
import referral_wallet_claims


ADAPTER = "referral_wallet"
SUPPORTED_RIGHTS = ("access", "portability")
MAX_LEDGER_ENTRIES = 200


def _account_id(value: object) -> str:
    raw = str(value or "").strip().lower()
    try:
        parsed = uuid.UUID(raw)
    except (ValueError, AttributeError) as exc:
        raise ValueError("accountId invalide") from exc
    if str(parsed) != raw:
        raise ValueError("accountId invalide")
    return raw


def _installation_id(value: object) -> str:
    return data_subject_rights._mobile_installation(value)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def snapshot(account_id: object) -> dict:
    """Return a bounded wallet export without exposing referred-customer identifiers.

    Ledger references are represented by hashes only. Reward rows are aggregated by
    state because their provider/external IDs identify third-party appointments and
    must not be disclosed to the wallet owner as part of this adapter.
    """
    account = _account_id(account_id)
    referral_engine.init_db()
    referral_wallet_claims.init_db()
    with analytics.connect() as db:
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
        ledger = db.execute(
            """SELECT kind,amount_cents,reference,created_at
               FROM referral_ledger WHERE account_id=?
               ORDER BY created_at DESC,id DESC LIMIT ?""",
            (account, MAX_LEDGER_ENTRIES),
        ).fetchall()
        total_ledger = int(
            db.execute(
                "SELECT COUNT(*) n FROM referral_ledger WHERE account_id=?",
                (account,),
            ).fetchone()["n"]
        )
    summary = referral_engine.account_summary(str(row["code"]))
    return {
        "account": {
            "accountId": str(row["id"]),
            "referralCode": str(row["code"]),
            "active": bool(row["active"]),
            "currency": str(row["currency"]),
            "rewardCents": int(row["reward_cents"]),
            "createdAt": str(row["created_at"]),
        },
        "wallet": {
            "balanceCents": int(summary["balanceCents"]),
            "pendingCents": int(summary["pendingCents"]),
        },
        "rewards": [
            {
                "status": str(item["status"]),
                "count": int(item["n"]),
                "rewardCents": int(item["cents"]),
            }
            for item in reward_rows
        ],
        "ledger": [
            {
                "kind": str(item["kind"]),
                "amountCents": int(item["amount_cents"]),
                "referenceHash": _hash(str(item["reference"])),
                "createdAt": str(item["created_at"]),
            }
            for item in ledger
        ],
        "ledgerCount": total_ledger,
        "ledgerTruncated": total_ledger > len(ledger),
        "thirdPartyAppointmentIdentifiersExposed": False,
    }


def execute(
    request_id: object,
    installation_id: object,
    account_id: object,
    db_path: Path | str | None = None,
) -> dict:
    """Execute access/portability for a wallet proven to belong to the DSAR subject."""
    rid = data_subject_rights._request_id(request_id)
    installation = _installation_id(installation_id)
    account = _account_id(account_id)
    row = data_subject_rights._request(rid, db_path)
    if str(row["status"]) not in {"open", "in_progress"}:
        raise RuntimeError("demande non exécutable")
    request_type = str(row["request_type"])
    if request_type not in SUPPORTED_RIGHTS:
        raise NotImplementedError("type de droit non pris en charge par cet adaptateur")
    if data_subject_rights._adapter_executed(rid, ADAPTER, db_path):
        raise RuntimeError("adaptateur déjà exécuté pour cette demande")

    installation_hash = _hash(installation)
    if not hmac.compare_digest(str(row["subject_ref_hash"]), installation_hash):
        raise PermissionError("référence du demandeur refusée")
    if not referral_wallet_claims.ownership_matches(account, installation):
        raise PermissionError("propriété de cagnotte non prouvée")

    data = snapshot(account)
    export_hash = _hash(
        json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    evidence = {
        "requestId": rid,
        "requestType": request_type,
        "adapter": ADAPTER,
        "ownershipProvenance": "authenticated_mobile_wallet_claim",
        "ledgerCount": int(data["ledgerCount"]),
        "ledgerTruncated": bool(data["ledgerTruncated"]),
        "thirdPartyAppointmentIdentifiersExposed": False,
        "exportHash": export_hash,
    }
    execution_id = data_subject_rights._audit_execution(
        row,
        ADAPTER,
        "export",
        evidence,
        db_path,
    )
    return {
        "ok": True,
        "requestId": rid,
        "requestType": request_type,
        "adapter": ADAPTER,
        "format": "application/json",
        "data": data,
        "executionId": execution_id,
        "requestStatus": "in_progress",
        "requestComplete": False,
    }


def capability(db_path: Path | str | None = None) -> dict:
    data_subject_rights._init_audit(db_path)
    with compliance_store.connect(db_path) as db:
        execution_count = int(
            db.execute(
                "SELECT COUNT(*) n FROM rights_execution_audit WHERE adapter=?",
                (ADAPTER,),
            ).fetchone()["n"]
        )
    owner = referral_wallet_claims.capability()
    return {
        "bound": True,
        "partial": True,
        "adapter": ADAPTER,
        "supportedRights": list(SUPPORTED_RIGHTS),
        "ownershipProvenance": owner["provenance"],
        "ownerEvidenceCount": int(owner["ownerEvidenceCount"]),
        "rawInstallationPersisted": False,
        "thirdPartyAppointmentIdentifiersExposed": False,
        "ledgerLimit": MAX_LEDGER_ENTRIES,
        "executionCount": execution_count,
        "remainingOperations": ["rectification_policy", "erasure_retention_policy"],
    }
