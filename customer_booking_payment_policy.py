"""Fail-closed payment decision for a Mercure customer booking.

Order of operations: the Mercure appointment is written first, then the
customer pays online through the CheckupAuto Payline checkout bound to that
confirmed appointment. The write gate therefore requires a verified online
policy but no prior receipt; payment is due right after the booking.
"""
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
    mode=policy.get("paymentMode")
    if required is not True or mode not in (None, "online"):
        raise BookingPaymentPolicyError("booking_online_payment_required")
    paid=False
    if payment_evidence is not None:
        # A receipt is never needed before the write, but a supplied one must
        # still be provider-verified rather than silently ignored.
        if (not isinstance(payment_evidence,dict) or payment_evidence.get("providerVerified") is not True
                or payment_evidence.get("paid") is not True):
            raise BookingPaymentPolicyError("booking_payment_unverified")
        paid=True
    return {"authorized":True,"paymentRequired":True,"paymentMode":"online",
            "paymentDue":"after_booking","paid":paid}
