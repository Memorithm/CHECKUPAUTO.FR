from __future__ import annotations

import re

import mobile_devices
import referral_wallet_claims


_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
_REFERRAL_WALLET_PREFIX = "rw_"


def claim_kind(token: object) -> str:
    raw = str(token or "").strip()
    if not _TOKEN_RE.fullmatch(raw):
        raise ValueError("claimToken invalide")
    return "referral_wallet" if raw.startswith(_REFERRAL_WALLET_PREFIX) else "vehicle"


def consume(payload: dict) -> dict:
    """Consume a typed mobile claim without mixing claim trust domains.

    Vehicle and referral-wallet claims deliberately keep independent validators and
    storage. This dispatcher classifies only the reserved token namespace, then lets
    the owning subsystem authenticate the installation and validate the claim.
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


def capability() -> dict:
    return {
        "bound": True,
        "claimTypes": ["vehicle", "referral_wallet"],
        "walletTokenPrefix": _REFERRAL_WALLET_PREFIX,
        "sharedEndpointReady": False,
        "rawClaimTokenPersisted": False,
    }
