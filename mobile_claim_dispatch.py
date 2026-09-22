from __future__ import annotations

import re

import mobile_authoritative_sync
import mobile_devices
import referral_wallet_claims


_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
_REFERRAL_WALLET_PREFIX = "rw_"
_VEHICLE_PREFIX = "vc_"


def claim_kind(token: object) -> str:
    raw = str(token or "").strip()
    if not _TOKEN_RE.fullmatch(raw):
        raise ValueError("claimToken invalide")
    return "referral_wallet" if raw.startswith(_REFERRAL_WALLET_PREFIX) else "vehicle"


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

    kind = claim_kind(payload.get("claimToken"))
    if kind == "referral_wallet":
        result = referral_wallet_claims.consume(payload)
        return {
            "ok": bool(result.get("ok")),
            "claimType": "referral_wallet",
            "claimedAt": result.get("claimedAt"),
            "provenance": result.get("provenance"),
        }

    result = mobile_devices.consume_vehicle_claim(payload)
    return {
        "ok": bool(result.get("ok")),
        "claimType": "vehicle",
        "bindingId": result.get("bindingId"),
        "claimedAt": result.get("claimedAt"),
    }


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
    try:
        mobile_authoritative_sync.sync_installation(
            str(payload.get("installationId") or "")
        )
    except Exception:
        pass
    return result


def capability() -> dict:
    return {
        "bound": True,
        "claimTypes": ["vehicle", "referral_wallet"],
        "vehicleTokenPrefix": _VEHICLE_PREFIX,
        "walletTokenPrefix": _REFERRAL_WALLET_PREFIX,
        "legacyVehicleTokensAccepted": True,
        "vehicleAuthoritativeRefreshBound": True,
        "sharedEndpointReady": True,
        "rawClaimTokenPersisted": False,
    }
