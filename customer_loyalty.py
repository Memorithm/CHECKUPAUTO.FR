"""Bridge a web customer loyalty wallet to the existing iOS wallet claim flow."""
from __future__ import annotations

import base64
import io
import re

import qrcode
import qrcode.image.svg

import customer_accounts
import referral_wallet_claims


class CustomerLoyaltyError(ValueError):
    pass


def _origin(value: object) -> str:
    raw=str(value or "").strip().rstrip("/")
    if not re.fullmatch(r"https://[A-Za-z0-9.-]+(?::[0-9]{1,5})?",raw):
        raise CustomerLoyaltyError("customer_loyalty_origin_invalid")
    return raw


def _qr_data_url(url: str) -> str:
    image=qrcode.make(
        url,
        image_factory=qrcode.image.svg.SvgPathImage,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=4,
    )
    buffer=io.BytesIO()
    image.save(buffer)
    return "data:image/svg+xml;base64,"+base64.b64encode(buffer.getvalue()).decode("ascii")


def issue_ios_claim(account_id: object, origin: object, ttl_seconds: int = 1800) -> dict:
    origin=_origin(origin)
    profile=customer_accounts.profile(account_id)
    code=str((profile.get("loyalty") or {}).get("referralCode") or "")
    if not code:
        raise CustomerLoyaltyError("customer_loyalty_wallet_missing")
    claim=referral_wallet_claims.issue(code,ttl_seconds)
    token=str(claim["claimToken"])
    url=f"{origin}/app/claim#token={token}"
    return {
        "ok":True,
        "claimType":"referral_wallet",
        "claimUrl":url,
        "qrDataUrl":_qr_data_url(url),
        "expiresAt":str(claim["expiresAt"]),
        "singleUse":True,
        "rawTokenPersisted":False,
    }
