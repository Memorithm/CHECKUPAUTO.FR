from __future__ import annotations

from pathlib import Path

import data_subject_rights
import referral_wallet_lifecycle


ADAPTER = "mobile_installation"
RIGHT = "erasure"


def _receipt_after_request(row) -> dict | None:
    receipt = referral_wallet_lifecycle.mobile_erasure_receipt_by_subject_hash(
        str(row["subject_ref_hash"])
    )
    if not receipt:
        return None
    erased_at = str(receipt.get("erasedAt") or "")
    received_at = str(row["received_at"] or "")
    if not erased_at or not received_at or erased_at < received_at:
        return None
    return receipt


def _removed_from_receipt(receipt: dict) -> dict:
    removed = receipt.get("removed") or {}
    return {
        "deviceRecords": max(0, int(removed.get("deviceRecords") or 0)),
        "deadlineRecords": max(0, int(removed.get("deadlineRecords") or 0)),
        "vehicleBindingRecords": max(0, int(removed.get("vehicleBindingRecords") or 0)),
    }


def execute(
    request_id: object,
    subject_ref: object,
    db_path: Path | str | None = None,
) -> dict:
    """Execute mobile erasure with recoverable proof before the audit boundary."""
    rid = data_subject_rights._request_id(request_id)
    row = data_subject_rights._request(rid, db_path)
    if str(row["status"]) not in {"open", "in_progress"}:
        raise RuntimeError("demande non exécutable")

    ref = str(subject_ref or "").strip()
    data_subject_rights._verify_subject(row, ref, ADAPTER, db_path)
    if str(row["request_type"]) != RIGHT:
        raise NotImplementedError("type de droit non pris en charge par cet adaptateur")
    if not data_subject_rights._adapter_can_retry_partial(rid, ADAPTER, db_path):
        raise RuntimeError("adaptateur déjà exécuté pour cette demande")

    installation_id = data_subject_rights._mobile_installation(ref)
    recovered = _receipt_after_request(row)
    if recovered:
        removed = _removed_from_receipt(recovered)
        evidence_hash = str(recovered.get("evidenceHash") or "")
        erased_at = str(recovered.get("erasedAt") or "")
        ownership_released = 0
        recovered_from_receipt = True
    else:
        release = referral_wallet_lifecycle._release_installation_ownership(installation_id)
        ownership_released = int(release["released"])
        erased = referral_wallet_lifecycle._erase_mobile_rows_with_receipt(
            installation_id,
            receipt_if_absent=True,
        )
        removed = dict(erased["removedCounts"])
        evidence_hash = str(erased["evidenceHash"])
        erased_at = str(erased["erasedAt"])
        recovered_from_receipt = False

    evidence = {
        "requestId": rid,
        "requestType": RIGHT,
        "adapter": ADAPTER,
        "removed": removed,
        "referralWalletOwnershipReleased": ownership_released,
        "mobileErasureEvidenceHash": evidence_hash,
        "erasedAt": erased_at,
        "recoveredFromReceipt": recovered_from_receipt,
    }
    execution_id = data_subject_rights._audit_execution(
        row,
        ADAPTER,
        "erase",
        evidence,
        db_path,
    )
    return {
        "ok": True,
        "requestId": rid,
        "requestType": RIGHT,
        "adapter": ADAPTER,
        "removed": removed,
        "referralWalletOwnershipReleased": ownership_released,
        "mobileErasureEvidenceHash": evidence_hash,
        "recoveredFromReceipt": recovered_from_receipt,
        "executionId": execution_id,
        "requestStatus": "in_progress",
        "requestComplete": False,
    }
