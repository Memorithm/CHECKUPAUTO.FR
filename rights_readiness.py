from __future__ import annotations

from pathlib import Path

import customer_account_rights
import data_subject_rights
import mercure_rectification_boundary
import referral_wallet_rights
import review_followup_rights
import rights_rectification
import rights_subject_bindings
import withdrawal_readiness


SUPPORTED_BINDING_PROVENANCE = (
    rights_subject_bindings.MOBILE_BINDING_PROVENANCE,
    rights_subject_bindings.MERCURE_APPOINTMENT_PROVENANCE,
)


def _wallet_capability(db_path: Path | str | None = None) -> dict:
    try:
        return referral_wallet_rights.capability(db_path)
    except Exception:
        return {
            "bound": False,
            "partial": True,
            "adapter": "referral_wallet",
            "supportedRights": [],
            "state": "unavailable",
            "remainingOperations": ["ownership_proof", "access", "portability", "rectification_policy", "erasure_retention_policy"],
        }


def capability(db_path: Path | str | None = None) -> dict:
    """Compose DSAR capability with cross-store proof and bounded adapters.

    ``data_subject_rights`` owns the central multi-store execution capability,
    ``rights_subject_bindings`` owns Mercure/contract proof provenance,
    ``rights_rectification`` exposes the deliberately bounded local correction
    path, ``mercure_rectification_boundary`` records whether an authoritative
    provider mutation primitive has actually been verified,
    ``referral_wallet_rights`` exposes only the wallet access/portability path
    after explicit mobile ownership proof, and ``withdrawal_readiness`` keeps
    withdrawal implementation separate from retention-policy executability. No
    partial adapter is allowed to flip the global ``bound`` flag.
    """
    result = dict(data_subject_rights.capability(db_path))
    recent = rights_subject_bindings.rows(db_path, limit=500)
    observed = sorted({
        str(row.get("provenance") or "")
        for row in recent
        if str(row.get("provenance") or "")
    })
    result["subjectBindingProvenance"] = list(SUPPORTED_BINDING_PROVENANCE)
    result["observedSubjectBindingProvenance"] = observed
    result["subjectBindingEvidenceObserved"] = bool(observed)

    rectification = rights_rectification.capability()
    result["rectificationExecution"] = rectification
    result["mercureRectification"] = mercure_rectification_boundary.capability()
    if rectification.get("partial"):
        adapter = str(rectification.get("adapter") or "").strip()
        request_type = str(rectification.get("requestType") or "").strip()
        if adapter and request_type:
            supported = dict(result.get("supportedAdapters") or {})
            supported[adapter] = [request_type]
            result["supportedAdapters"] = supported

            partial = set(result.get("partialSystemAdapters") or [])
            partial.add(adapter)
            result["partialSystemAdapters"] = sorted(partial)

            partial_rights = set(result.get("partiallySupportedRightTypes") or [])
            partial_rights.add(request_type)
            result["partiallySupportedRightTypes"] = sorted(partial_rights)

    wallet = _wallet_capability(db_path)
    result["referralWalletExecution"] = wallet
    if wallet.get("bound"):
        supported = dict(result.get("supportedAdapters") or {})
        supported["referral_wallet"] = list(wallet.get("supportedRights") or [])
        result["supportedAdapters"] = supported
        partial = set(result.get("partialSystemAdapters") or [])
        partial.add("referral_wallet")
        result["partialSystemAdapters"] = sorted(partial)

    review_followup=review_followup_rights.capability()
    result["reviewFollowupExecution"]=review_followup
    if review_followup.get("bound"):
        supported=dict(result.get("supportedAdapters") or {})
        supported[review_followup_rights.ADAPTER]=list(
            review_followup.get("supportedRights") or []
        )
        result["supportedAdapters"]=supported

    customer_account=customer_account_rights.capability()
    result["customerAccountExecution"]=customer_account
    if customer_account.get("bound"):
        supported=dict(result.get("supportedAdapters") or {})
        supported[customer_account_rights.ADAPTER]=list(
            customer_account.get("supportedRights") or []
        )
        result["supportedAdapters"]=supported

    result["providerKeyedErasureExecution"] = {
        "implemented": True,
        "partial": True,
        "directMercureSubjectOnly": True,
        "providerAppointmentCoverageRequired": True,
        "encryptedCrashPlan": True,
        "crossStoreCompletionEvidence": True,
        "rawAppointmentIdsPersistedInCompliance": False,
        "completionEligibleForGlobalCoverage": False,
    }

    withdrawal = withdrawal_readiness.capability(db_path)
    result["withdrawalEvidenceExecution"] = withdrawal
    withdrawal_rights = [
        str(value)
        for value in (withdrawal.get("supportedRights") or [])
        if str(value)
    ]
    if withdrawal_rights:
        supported = dict(result.get("supportedAdapters") or {})
        supported[str(withdrawal.get("adapter") or "withdrawal_evidence")] = withdrawal_rights
        result["supportedAdapters"] = supported
        partial = set(result.get("partialSystemAdapters") or [])
        partial.add(str(withdrawal.get("adapter") or "withdrawal_evidence"))
        result["partialSystemAdapters"] = sorted(partial)
    return result
