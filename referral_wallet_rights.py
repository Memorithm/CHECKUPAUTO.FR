from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import sqlite3
import uuid
from pathlib import Path

import compliance_store
import data_subject_rights
import referral_wallet_claims
import referral_wallet_erasure
import referral_wallet_paged_export


ADAPTER = "referral_wallet"
SUPPORTED_RIGHTS = ("access", "portability", "erasure")
MAX_LEDGER_ENTRIES = referral_wallet_paged_export.PAGE_SIZE
PAGED_EXPORT_ORPHAN_GRACE_SECONDS = 30


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


def _recover_stale_orphaned_paged_export(
    request_id: str,
    request_type: str,
    account_id: str,
    db_path: Path | str | None = None,
) -> bool:
    """Delete only a stale paged-export session that never acquired audit proof.

    ``referral_wallet_paged_export.begin`` commits its opaque session before the
    adapter writes the initial ``export_bounded`` audit row. A process crash in
    that narrow gap used to make the request permanently non-retryable because a
    later begin found the unique request session and stopped. Recovery is allowed
    only when the session is still active, belongs to the same request type and
    hashed wallet, has no rights-execution evidence, and is older than a short
    grace period that protects a concurrent in-flight execution.
    """
    data_subject_rights._init_audit(db_path)
    now = datetime.datetime.fromisoformat(data_subject_rights._now_iso())
    with compliance_store.connect(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            session = db.execute(
                """SELECT session_id,request_type,account_hash,created_at,
                          completed_at,invalidated_at
                   FROM referral_wallet_export_session WHERE request_id=?""",
                (request_id,),
            ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return False
            raise
        if not session:
            return False

        evidence = db.execute(
            """SELECT 1 FROM rights_execution_audit
               WHERE request_id=? AND adapter=? LIMIT 1""",
            (request_id, ADAPTER),
        ).fetchone()
        if evidence:
            raise RuntimeError("session d'export paginé déjà auditée")
        if str(session["completed_at"]) or str(session["invalidated_at"]):
            raise RuntimeError("session d'export paginé non récupérable")
        if str(session["request_type"]) != request_type:
            raise RuntimeError("type de demande de session incohérent")
        if not hmac.compare_digest(str(session["account_hash"]), _hash(account_id)):
            raise PermissionError("cagnotte de session refusée")

        created_at = datetime.datetime.fromisoformat(str(session["created_at"]))
        age_seconds = (now - created_at).total_seconds()
        if age_seconds < PAGED_EXPORT_ORPHAN_GRACE_SECONDS:
            raise RuntimeError("session d'export paginé encore active")

        db.execute(
            "DELETE FROM referral_wallet_export_session WHERE request_id=?",
            (request_id,),
        )
        return True


def snapshot(account_id: object) -> dict:
    """Return the privacy-bounded first page of a wallet export.

    Large ledgers are exposed through the stable paged-export session started by
    ``execute``. The standalone snapshot remains bounded and never exposes raw
    reward/provider appointment identifiers.
    """
    return referral_wallet_paged_export.snapshot(account_id)


def execute(
    request_id: object,
    installation_id: object,
    account_id: object,
    db_path: Path | str | None = None,
) -> dict:
    """Execute a referral-wallet right for its proven mobile owner.

    Access and portability return a complete bounded snapshot for small ledgers.
    Oversized ledgers stage a stable paged session and record ``export_bounded``;
    the later continuation appends ``export_complete`` only after every row in
    the original boundary is delivered and the full rolling proof re-verifies.
    Erasure remains a retention-aware two-stage operation.
    """
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

    if request_type in {"access", "portability"}:
        if not referral_wallet_claims.ownership_matches(account, installation):
            raise PermissionError("propriété de cagnotte non prouvée")
        try:
            staged = referral_wallet_paged_export.begin(
                rid,
                installation,
                account,
                db_path,
            )
        except RuntimeError as exc:
            if str(exc) != "session d'export paginé déjà existante":
                raise
            recovered = _recover_stale_orphaned_paged_export(
                rid,
                request_type,
                account,
                db_path,
            )
            if not recovered:
                raise
            staged = referral_wallet_paged_export.begin(
                rid,
                installation,
                account,
                db_path,
            )
        data = staged["data"]
        export_complete = bool(staged["exportComplete"])
        paged_export = staged.get("pagedExport")
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
            "exportComplete": export_complete,
            "thirdPartyAppointmentIdentifiersExposed": False,
            "exportHash": export_hash,
        }
        if paged_export:
            evidence.update(
                {
                    "pagedExportStarted": True,
                    "pagedExportSessionHash": _hash(str(paged_export["sessionId"])),
                    "pageSize": int(paged_export["pageSize"]),
                    "stableBoundary": bool(paged_export["stableBoundary"]),
                    "snapshotChainHash": str(paged_export["snapshotChainHash"]),
                }
            )
        execution_id = data_subject_rights._audit_execution(
            row,
            ADAPTER,
            "export_complete" if export_complete else "export_bounded",
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
            "exportComplete": export_complete,
            "pagedExport": paged_export,
            "executionId": execution_id,
            "requestStatus": "in_progress",
            "requestComplete": False,
        }

    erased = referral_wallet_erasure.execute(
        rid,
        installation,
        account,
        db_path,
    )
    evidence = {
        "requestId": rid,
        "requestType": request_type,
        "adapter": ADAPTER,
        "ownershipProvenance": "authenticated_mobile_wallet_claim",
        "accountDeactivated": bool(erased["accountDeactivated"]),
        "referralCodePseudonymized": bool(erased["referralCodePseudonymized"]),
        "referralCodeChanged": bool(erased["referralCodeChanged"]),
        "attributionTokensCleared": int(erased["attributionTokensCleared"]),
        "ownershipReleased": int(erased["ownershipReleased"]),
        "pendingClaimsRevoked": int(erased["pendingClaimsRevoked"]),
        "balanceCentsAtErasure": int(erased["balanceCentsAtErasure"]),
        "pendingRewardsAtErasure": int(erased["pendingRewardsAtErasure"]),
        "retainedFinancialRecords": dict(erased["retainedFinancialRecords"]),
        "retentionRuleId": str(erased["retention"]["ruleId"]),
        "retentionDays": int(erased["retention"]["activeDays"]),
        "legalReviewConfirmed": bool(erased["retention"]["legalReviewConfirmed"]),
        "financialHistoryRetained": True,
        "thirdPartyAppointmentIdentifiersExposed": False,
    }
    execution_id = data_subject_rights._audit_execution(
        row,
        ADAPTER,
        "deactivate_retained_erasure",
        evidence,
        db_path,
    )
    referral_wallet_erasure.finalize(rid, db_path)
    return {
        "ok": True,
        "requestId": rid,
        "requestType": request_type,
        "adapter": ADAPTER,
        "accountDeactivated": bool(erased["accountDeactivated"]),
        "referralCodePseudonymized": bool(erased["referralCodePseudonymized"]),
        "attributionTokensCleared": int(erased["attributionTokensCleared"]),
        "ownershipReleased": int(erased["ownershipReleased"]),
        "pendingClaimsRevoked": int(erased["pendingClaimsRevoked"]),
        "retainedFinancialRecords": dict(erased["retainedFinancialRecords"]),
        "retention": dict(erased["retention"]),
        "financialHistoryRetained": True,
        "finalPhysicalPurgeComplete": False,
        "executionId": execution_id,
        "requestStatus": "in_progress",
        "requestComplete": False,
    }


def continue_export(
    request_id: object,
    installation_id: object,
    account_id: object,
    session_id: object,
    db_path: Path | str | None = None,
) -> dict:
    """Continue a previously staged large-ledger export session."""
    return referral_wallet_paged_export.continue_export(
        request_id,
        installation_id,
        account_id,
        session_id,
        db_path,
    )


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
    erasure = referral_wallet_erasure.capability(db_path)
    paged = referral_wallet_paged_export.capability(db_path)
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
        "completeAccessOrPortabilityWhenLedgerNotTruncated": True,
        "largeLedgerPagedExport": paged,
        "executionCount": execution_count,
        "erasure": erasure,
        "remainingOperations": [
            "rectification_policy",
            "final_retention_expiry_purge",
        ],
    }
