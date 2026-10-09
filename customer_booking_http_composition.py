"""Trusted HTTP composition. Never accepts provider credentials from request JSON."""
from __future__ import annotations

import customer_booking_trusted_executor
import customer_booking_trusted_route_context


class BookingHttpCompositionError(ValueError):
    pass


def prepare(*, service: str, server_config: dict,
            payment_policy: dict, payment_evidence: dict | None):
    try:
        context=customer_booking_trusted_route_context.build(
            service=service,server_config=server_config,
            payment_policy=payment_policy,payment_evidence=payment_evidence)
    except (ValueError,TypeError) as exc:
        raise BookingHttpCompositionError("booking_provider_context_unqualified") from exc
    return customer_booking_trusted_executor.execute,context
