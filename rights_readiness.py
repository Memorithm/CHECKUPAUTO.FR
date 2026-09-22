from __future__ import annotations

from pathlib import Path

import data_subject_rights
import referral_wallet_rights
import rights_rectification
import rights_subject_bindings


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
    path, and ``referral_wallet_rights`` exposes only the wallet access/portability
    path after explicit mobile ownership proof. No partial adapter is allowed to
    flip the global ``bound`` flag.
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
    result["rectificationExecution"] = rights_rectification.capability()

    wallet = _wallet_capability(db_path)
    result["referralWalletExecution"] = wallet
    if wallet.get("bound"):
        supported = dict(result.get("supportedAdapters") or {})
        supported["referral_wallet"] = list(wallet.get("supportedRights") or [])
        result["supportedAdapters"] = supported
        partial = set(result.get("partialSystemAdapters") or [])
        partial.add("referral_wallet")
        result["partialSystemAdapters"] = sorted(partial)
    return result
