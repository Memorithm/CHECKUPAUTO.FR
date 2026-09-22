from __future__ import annotations

import hashlib

import analytics_store as analytics
import mobile_devices
import referral_wallet_claims


def _installation_hash(installation_id: str) -> str:
    return hashlib.sha256(installation_id.encode("utf-8")).hexdigest()


def release_for_authenticated_installation(payload: dict) -> dict:
    """Release wallet ownership evidence before deleting a mobile installation.

    The caller must prove the current installation identity. Only the SHA-256
    installation hash is used to locate durable wallet ownership evidence; neither
    the raw installation id nor registration secret is persisted in the wallet DB.
    This operation is intentionally performed before the mobile installation row is
    deleted so authentication cannot be bypassed or become impossible to retry.
    """
    if not isinstance(payload, dict):
        raise ValueError("payload invalide")
    if set(payload) != {"installationId", "registrationSecret"}:
        raise ValueError("payload invalide")

    installation_id = mobile_devices._install_id(payload.get("installationId"))
    secret_hash = mobile_devices._hash(
        mobile_devices._secret(payload.get("registrationSecret"))
    )
    mobile_devices.init_db()
    with mobile_devices.connect() as db:
        mobile_devices._authenticated_installation(db, installation_id, secret_hash)

    referral_wallet_claims.init_db()
    installation_hash = _installation_hash(installation_id)
    with analytics.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        cursor = db.execute(
            "DELETE FROM referral_wallet_owner WHERE installation_hash=?",
            (installation_hash,),
        )
        released = max(0, int(cursor.rowcount or 0))

    return {
        "ok": True,
        "released": released,
        "rawInstallationPersisted": False,
    }


def delete_installation(payload: dict) -> dict:
    """Release referral-wallet ownership, then delete the mobile installation.

    A wallet-release failure aborts before mobile deletion. This prevents a durable
    ownership proof from being stranded on an installation that no longer exists.
    """
    release = release_for_authenticated_installation(payload)
    result = mobile_devices.delete_installation(payload)
    return {
        **result,
        "referralWalletOwnershipReleased": int(release["released"]),
    }
