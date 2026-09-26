from __future__ import annotations

import re
import threading

import mobile_authoritative_sync
import mobile_devices
import privacy_suppression as privacy
import referral_wallet_claims
import referral_wallet_mobile


_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
_REFERRAL_WALLET_PREFIX = "rw_"
_VEHICLE_PREFIX = "vc_"
_WALLET_FIELDS = (
    "referralCode",
    "active",
    "currency",
    "rewardCents",
    "balanceCents",
    "pendingCents",
    "earnedReferrals",
    "pendingReferrals",
    "cancelledReferrals",
    "reversedReferrals",
)


def claim_kind(token: object) -> str:
    raw = str(token or "").strip()
    if not _TOKEN_RE.fullmatch(raw):
        raise ValueError("claimToken invalide")
    return "referral_wallet" if raw.startswith(_REFERRAL_WALLET_PREFIX) else "vehicle"


def _assert_installation_processing_allowed(value: object) -> str:
    """Reject new ownership mutations after installation-wide suppression.

    The shared claim endpoint is the public trust boundary for both vehicle and
    referral-wallet ownership. An ``all_processing`` restriction/erasure must
    therefore be checked before either claim domain can mutate its own store.
    """
    installation = mobile_devices._install_id(value)
    if privacy.is_suppressed("installation", installation, "all_processing"):
        raise PermissionError("traitement mobile refusé")
    return installation


def _project_wallet_status(status: object) -> dict | None:
    """Project only the public wallet read model at the mobile trust boundary."""
    if not isinstance(status, dict) or status.get("ok") is not True:
        return None
    if status.get("ownershipProvenance") != "authenticated_mobile_wallet_claim":
        return None
    for flag in (
        "shareCodeIsOwnershipProof",
        "accountIdentifiersExposed",
        "thirdPartyAppointmentIdentifiersExposed",
        "ledgerReferencesExposed",
    ):
        if status.get(flag) is not False:
            return None
    raw_wallets = status.get("wallets")
    if not isinstance(raw_wallets, list):
        return None
    wallets = []
    for row in raw_wallets:
        if not isinstance(row, dict):
            return None
        wallets.append({field: row.get(field) for field in _WALLET_FIELDS})
    return {
        "ok": True,
        "walletCount": len(wallets),
        "wallets": wallets,
        "ownershipProvenance": "authenticated_mobile_wallet_claim",
        "shareCodeIsOwnershipProof": False,
        "accountIdentifiersExposed": False,
        "thirdPartyAppointmentIdentifiersExposed": False,
        "ledgerReferencesExposed": False,
    }


def _wallet_status_after_claim(payload: dict) -> dict | None:
    """Return a bounded post-claim wallet snapshot without changing claim success.

    The ownership claim is single-use and commits before this read model is built.
    A transient status-read failure must therefore never turn a successfully
    consumed claim into an ambiguous client-side failure. Only the already
    authenticated installation identity is forwarded; the raw claim token is not.
    """
    try:
        status = referral_wallet_mobile.status(
            {
                "installationId": payload.get("installationId"),
                "registrationSecret": payload.get("registrationSecret"),
            }
        )
    except Exception:
        return None
    return _project_wallet_status(status)


def consume(payload: dict) -> dict:
    """Consume a typed mobile claim without mixing claim trust domains.

    Vehicle and referral-wallet claims deliberately keep independent validators and
    storage. New vehicle tokens use the reserved ``vc_`` namespace while legacy
    vehicle tokens remain classifiable as vehicle during migration. Wallet tokens
    are always routed to the dedicated ``rw_`` trust domain and are never allowed
    to fall through to the vehicle store.
    """
    if not isinstance(payload, dict):
        raise ValueError("payload invalide")
    if set(payload) != {"installationId", "registrationSecret", "claimToken"}:
        raise ValueError("payload invalide")

    _assert_installation_processing_allowed(payload.get("installationId"))
    kind = claim_kind(payload.get("claimToken"))
    if kind == "referral_wallet":
        result = referral_wallet_claims.consume(payload)
        response = {
            "ok": bool(result.get("ok")),
            "claimType": "referral_wallet",
            "claimedAt": result.get("claimedAt"),
            "provenance": result.get("provenance"),
        }
        wallet_status = _wallet_status_after_claim(payload)
        if wallet_status is not None:
            response["walletStatus"] = wallet_status
        return response

    result = mobile_devices.consume_vehicle_claim(payload)
    return {
        "ok": bool(result.get("ok")),
        "claimType": "vehicle",
        "bindingId": result.get("bindingId"),
        "claimedAt": result.get("claimedAt"),
    }


def _refresh_vehicle_claim(installation_id: str) -> None:
    try:
        mobile_authoritative_sync.sync_installation(
            installation_id,
            refresh_appointments=True,
        )
    except Exception:
        pass


def _start_authoritative_refresh(installation_id: str) -> None:
    threading.Thread(
        target=_refresh_vehicle_claim,
        args=(installation_id,),
        name="mobile-claim-authoritative-refresh",
        daemon=True,
    ).start()


def consume_with_authoritative_refresh(payload: dict) -> dict:
    """Consume a typed claim and refresh Mercure data only for vehicle claims.

    The public HTTP surface historically refreshed authoritative Mercure inventory
    after a successful vehicle claim and treated refresh failures as best-effort.
    Keep that behavior at this trust boundary while guaranteeing that referral
    wallet claims never trigger a Mercure synchronization.
    """
    result = consume(payload)
    if result.get("claimType") != "vehicle":
        return result
    _start_authoritative_refresh(str(payload.get("installationId") or ""))
    return result


def capability() -> dict:
    return {
        "bound": True,
        "claimTypes": ["vehicle", "referral_wallet"],
        "vehicleTokenPrefix": _VEHICLE_PREFIX,
        "walletTokenPrefix": _REFERRAL_WALLET_PREFIX,
        "legacyVehicleTokensAccepted": True,
        "vehicleAuthoritativeRefreshBound": True,
        "installationAllProcessingGuard": True,
        "walletStatusAfterClaim": "best_effort_verified_read_model",
        "sharedEndpointReady": True,
        "rawClaimTokenPersisted": False,
    }
