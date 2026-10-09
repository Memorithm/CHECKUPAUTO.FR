"""Trusted HTTP booking composition; no browser authority or automatic activation."""
from __future__ import annotations

import customer_booking_trusted_executor
import customer_booking_trusted_route_context


class BookingHttpCompositionUnavailable(RuntimeError):
    pass


def build(*, payload: dict, server_config: dict,
          payment_policy: dict, payment_evidence: dict | None) -> dict:
    if not isinstance(payload,dict) or payload.get("service") not in {"technical","fitted"}:
        raise BookingHttpCompositionUnavailable("booking_service_invalid")
    context=customer_booking_trusted_route_context.build(
        service=payload["service"],server_config=server_config,
        payment_policy=payment_policy,payment_evidence=payment_evidence)
    return {"executor":customer_booking_trusted_executor.execute,
            "trusted_context":context}
