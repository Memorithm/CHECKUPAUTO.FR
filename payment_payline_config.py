"""Explicit Payline/Monext sandbox configuration; sandbox transport only, no live payments.

Acquiring-bank TPE/BIN/NLSA/Mastercard references are not API credentials.
Only the named API fields from the merchant administration centre are accepted.
Format validation does not verify ownership, contract activation or capabilities.
"""
from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

SANDBOX_WEBPAYMENT_ENDPOINT = "https://homologation.payline.com/V4/services/WebPaymentAPI"
REQUIRED_FIELDS = ("environment", "merchantId", "accessKey", "contractNumber", "publicOrigin")


class PaylineConfigurationError(ValueError):
    """Stable error codes only: never echo submitted identifiers or secrets."""


def _value(value: object, pattern: str, code: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise PaylineConfigurationError(code)
    return value


def _origin(value: object) -> str:
    if (not isinstance(value, str) or not value.isascii() or len(value) > 255
            or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value)
            or "\\" in value):
        raise PaylineConfigurationError("payline_https_origin_required")
    try:
        url = urlsplit(value)
        valid = (url.scheme == "https" and url.hostname and url.username is None
                 and url.password is None and url.port in (None, 443)
                 and url.path in ("", "/") and "?" not in value and "#" not in value
                 and not url.netloc.endswith(":")
                 and re.fullmatch(r"[A-Za-z0-9.-]{1,253}", url.hostname))
        if valid:
            labels = url.hostname.split(".")
            valid = len(labels) >= 2 and all(
                re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
                for label in labels
            )
    except ValueError:
        valid = False
    if not valid:
        raise PaylineConfigurationError("payline_https_origin_required")
    return value.rstrip("/")


@dataclass(frozen=True)
class PaylineSandboxConfig:
    # repr deliberately excludes identifiers, credentials and the merchant URL.
    merchant_id: str = field(repr=False)
    access_key: str = field(repr=False)
    contract_number: str = field(repr=False)
    public_origin: str = field(repr=False)
    environment: str = "sandbox"

    def __post_init__(self):
        if self.environment != "sandbox":
            raise PaylineConfigurationError("payline_sandbox_required")
        # These are bounded project input policies, not proof of valid accounts.
        _value(self.merchant_id, r"[0-9]{1,32}", "payline_merchant_id_invalid")
        _value(self.access_key, r"[\x21-\x7e]{1,256}", "payline_access_key_invalid")
        _value(self.contract_number, r"[A-Za-z0-9_-]{1,20}", "payline_contract_number_invalid")
        _origin(self.public_origin)

    @classmethod
    def from_mapping(cls, values: dict) -> PaylineSandboxConfig:
        """Trusted private configuration only, never browser checkout input.

        No aliases, guessing from bank names, or copying of a terminal identifier
        into an API field. Leading zeroes are retained and integers are rejected.
        """
        if not isinstance(values, dict) or set(values) != set(REQUIRED_FIELDS):
            raise PaylineConfigurationError("payline_explicit_api_fields_required")
        return cls(
            merchant_id=values["merchantId"], access_key=values["accessKey"],
            contract_number=values["contractNumber"], public_origin=values["publicOrigin"],
            environment=values["environment"],
        )

    @property
    def webpayment_endpoint(self) -> str:
        return SANDBOX_WEBPAYMENT_ENDPOINT

    def authentication_headers(self) -> dict[str, str]:
        """For the sandbox TLS API transport only. Do not log or send to browsers."""
        encoded = base64.b64encode((self.merchant_id + ":" + self.access_key).encode("ascii"))
        return {"Authorization": "Basic " + encoded.decode("ascii")}


def preflight(config: PaylineSandboxConfig | None = None) -> dict:
    """A local syntax report, never an online authentication/readiness claim."""
    if config is not None and not isinstance(config, PaylineSandboxConfig):
        raise PaylineConfigurationError("payline_configuration_type_invalid")
    blockers = ["provider_authentication_unverified", "contract_binding_unverified",
                "checkout_not_bound"]
    if config is None:
        blockers.insert(0, "explicit_api_configuration_missing")
    return {
        "provider": "payline", "providerLabel": "Payline / Monext",
        "environment": "sandbox", "providerEnvironment": "homologation",
        "configurationSyntaxValid": config is not None,
        "requiredFields": list(REQUIRED_FIELDS),
        "credentialsVerified": False, "contractBindingVerified": False,
        "transportImplemented": True, "checkoutBound": False,
        "httpCallbacksBound": True, "livePaymentsEnabled": False,
        "ready": False, "blockingReasons": blockers,
    }
