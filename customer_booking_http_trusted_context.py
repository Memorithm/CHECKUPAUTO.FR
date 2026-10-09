"""Server-side booking composition for the authenticated customer HTTP route.

No browser-controlled provider metadata or payment policy is accepted.
Missing trusted configuration fails closed without a Mercure write.
"""
from __future__ import annotations

import customer_booking_trusted_route_context
import customer_booking_trusted_executor
import mercure_vl_payment_policy_source


class BookingHttpContextError(ValueError):
    pass


def prepare(*, service: str, server_config: dict,
            payment_policy: dict | None = None, payment_evidence: dict | None = None,
            date: str | None = None, time: str | None = None):
    if not isinstance(server_config,dict) or server_config.get("enabled") is not True:
        raise BookingHttpContextError("booking_server_not_qualified")
    if service not in {"technical", "fitted"}:
        raise BookingHttpContextError("booking_service_invalid")
    if payment_policy is None:
        try:
            payment_policy = mercure_vl_payment_policy_source.load(service=service)
        except mercure_vl_payment_policy_source.MercurePaymentPolicyError as exc:
            raise BookingHttpContextError(str(exc)) from None
        except Exception:
            raise BookingHttpContextError("booking_payment_policy_unqualified") from None
    if not isinstance(payment_policy,dict) or payment_policy.get("providerVerified") is not True:
        raise BookingHttpContextError("booking_payment_policy_unqualified")
    context=customer_booking_trusted_route_context.build(
        service=service,server_config=server_config,
        payment_policy=payment_policy,payment_evidence=payment_evidence,date=date,time=time)
    return customer_booking_trusted_executor.execute,context
