from __future__ import annotations

import hashlib
import hmac
import json
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
