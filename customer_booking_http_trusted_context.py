"""Server-side booking composition for the authenticated customer HTTP route.

No browser-controlled provider metadata or payment policy is accepted.
Missing trusted configuration fails closed without a Mercure write.
"""
from __future__ import annotations

import customer_booking_trusted_route_context
import customer_booking_trusted_executor


class BookingHttpContextError(ValueError):
    pass


def prepare(*, service: str, server_config: dict,
            payment_policy: dict, payment_evidence: dict | None):
    if not isinstance(server_config,dict) or server_config.get("enabled") is not True:
        raise BookingHttpContextError("booking_server_not_qualified")
    context=customer_booking_trusted_route_context.build(
        service=service,server_config=server_config,
        payment_policy=payment_policy,payment_evidence=payment_evidence)
    return customer_booking_trusted_executor.execute,context
