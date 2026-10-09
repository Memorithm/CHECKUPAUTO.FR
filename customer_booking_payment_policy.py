"""Fail-closed payment decision for a Mercure customer booking."""
from __future__ import annotations


class BookingPaymentPolicyError(ValueError):
    pass


def authorize(*, service: str, policy: dict, payment_evidence: dict | None = None) -> dict:
    if not isinstance(policy,dict) or policy.get("service")!=service:
        raise BookingPaymentPolicyError("booking_payment_policy_unverified")
    if policy.get("providerVerified") is not True:
        raise BookingPaymentPolicyError("booking_payment_policy_unverified")
    required=policy.get("paymentRequired")
    if type(required) is not bool:
        raise BookingPaymentPolicyError("booking_payment_policy_unverified")
    if required:
        if not isinstance(payment_evidence,dict):
            raise BookingPaymentPolicyError("booking_payment_evidence_missing")
        if payment_evidence.get("providerVerified") is not True or payment_evidence.get("paid") is not True:
            raise BookingPaymentPolicyError("booking_payment_unverified")
    return {"authorized":True,"paymentRequired":required}
