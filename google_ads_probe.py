"""Least-privilege Google Ads API connectivity probe.

This module deliberately does not persist OAuth or developer-token credentials.  It
accepts already-resolved credentials, performs the read-only
``customers:listAccessibleCustomers`` request, validates the response shape, and
returns only aggregate state suitable for observability.
"""

import re

import requests

GOOGLE_ADS_SCOPE = "https://www.googleapis.com/auth/adwords"
GOOGLE_ADS_API_VERSION = "v25"
GOOGLE_ADS_ACCESSIBLE_CUSTOMERS_URL = (
    f"https://googleads.googleapis.com/{GOOGLE_ADS_API_VERSION}/"
    "customers:listAccessibleCustomers"
)
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
_CUSTOMER_RESOURCE = re.compile(r"^customers/[0-9]+$")


class GoogleAdsProbeError(RuntimeError):
    """Base error for a secret-safe Google Ads verification failure."""


class GoogleAdsProbeHTTPError(GoogleAdsProbeError):
    """HTTP failure with bounded diagnostics and retry classification."""

    def __init__(self, message, *, status=0, retry_after="", retryable=False):
        self.status = int(status or 0)
        self.retry_after = str(retry_after or "")[:80]
        self.retryable = bool(retryable)
        super().__init__(str(message or "Google Ads verification failed")[:180])


def verify_access(access_token, developer_token, *, request_get=requests.get, timeout=20):
    """Verify Google Ads credentials without mutating remote state.

    ``ListAccessibleCustomers`` requires the existing ``adwords`` OAuth scope and
    a developer token.  The returned customer resource names are validated but
    never exposed; only their count and whether at least one directly accessible
    customer exists are returned.
    """

    access = str(access_token or "").strip()
    developer = str(developer_token or "").strip()
    if not access:
        raise GoogleAdsProbeError("Jeton OAuth Google Ads requis.")
    if not developer:
        raise GoogleAdsProbeError("Jeton développeur Google Ads requis.")
    if len(access) > 8192 or len(developer) > 512:
        raise GoogleAdsProbeError("Identifiants Google Ads invalides.")

    try:
        response = request_get(
            GOOGLE_ADS_ACCESSIBLE_CUSTOMERS_URL,
            headers={
                "Authorization": "Bearer " + access,
                "developer-token": developer,
            },
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise GoogleAdsProbeHTTPError(
            "Connexion à Google Ads impossible.",
            retryable=True,
        ) from exc

    if response.status_code >= 400:
        status_code = int(response.status_code)
        raise GoogleAdsProbeHTTPError(
            "Google Ads a refusé la vérification des comptes accessibles.",
            status=status_code,
            retry_after=response.headers.get("Retry-After", ""),
            retryable=status_code in _RETRYABLE_STATUSES,
        )

    try:
        payload = response.json()
    except (TypeError, ValueError) as exc:
        raise GoogleAdsProbeError("Réponse Google Ads invalide.") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("resourceNames"), list):
        raise GoogleAdsProbeError("Réponse Google Ads invalide.")

    names = payload["resourceNames"]
    normalized = []
    seen = set()
    for value in names:
        if not isinstance(value, str):
            raise GoogleAdsProbeError("Réponse Google Ads invalide.")
        resource = value.strip()
        if not _CUSTOMER_RESOURCE.fullmatch(resource):
            raise GoogleAdsProbeError("Réponse Google Ads invalide.")
        if resource not in seen:
            normalized.append(resource)
            seen.add(resource)

    return {
        "verification": "verified",
        "usable": bool(normalized),
        "accessibleCustomerCount": len(normalized),
    }
