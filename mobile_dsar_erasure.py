from __future__ import annotations

from pathlib import Path

import data_subject_rights
import mobile_devices
import notification_privacy
import privacy_suppression
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


def _push_recipient_key(installation_id: str) -> str:
    """Return the transient broker recipient key before the mobile row is erased."""
    mobile_devices.init_db()
    with mobile_devices.connect() as db:
        row = db.execute(
            """SELECT device_token,environment FROM mobile_device
               WHERE installation_id=? LIMIT 1""",
            (installation_id,),
        ).fetchone()
    if not row:
        return ""
    token = str(row["device_token"] or "").strip().lower()
    environment = str(row["environment"] or "").strip().lower()
    if not token or environment not in {"sandbox", "production"}:
        return ""
    return f"{environment}:{token}"


def _erase_notification_privacy(installation_id: str) -> dict:
    """Stop retryable marketing pushes and remove subject-to-recipient linkage.

    The broker keeps already-sent delivery evidence, but the pseudonymous bridge
    that links the installation subject to a recipient hash is physically removed.
    An active transport lease makes this step retryable instead of claiming an
    erasure while a delivery is still in flight.
    """
    subject_hash = privacy_suppression.identity_hash("installation", installation_id)
    recipient_key = _push_recipient_key(installation_id)
    suppression = notification_privacy.suppress_retryable_marketing(
        subject_hash,
        "push",
        fallback_recipient_key=recipient_key,
    )
    if int(suppression.get("inFlightRows") or 0):
        raise RuntimeError("effacement NotificationBroker différé: livraison en cours")
    binding = notification_privacy.erase_subject_bindings(subject_hash, "push")
    return {
        "retryableDeliveriesSuppressed": max(0, int(suppression.get("affectedRows") or 0)),
        "retainedSentDeliveries": max(0, int(suppression.get("retainedSentRows") or 0)),
        "privacyBindingsRemoved": max(0, int(binding.get("affectedRows") or 0)),
        "remainingPrivacyBindings": max(0, int(binding.get("remainingActiveRows") or 0)),
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
    notification_privacy_erasure = _erase_notification_privacy(installation_id)
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
        "notificationPrivacy": notification_privacy_erasure,
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
        "notificationPrivacy": notification_privacy_erasure,
        "mobileErasureEvidenceHash": evidence_hash,
        "recoveredFromReceipt": recovered_from_receipt,
        "executionId": execution_id,
        "requestStatus": "in_progress",
        "requestComplete": False,
    }
