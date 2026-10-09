"""Server-side dependency injection for the authenticated customer booking route.

Provider metadata and payment evidence must originate from server callbacks,
never from the customer POST body. Production writes remain disabled unless
an independently qualified server policy explicitly authorizes them.
"""
from __future__ import annotations

import customer_booking_trusted_executor
import customer_booking_trusted_route_context


class BookingHttpCompositionUnavailable(RuntimeError):
    pass


def compose(*, payload: dict, server_config_loader, payment_policy_loader,
            payment_evidence_loader):
    if not isinstance(payload,dict) or payload.get("service") not in {"technical","fitted"}:
        raise BookingHttpCompositionUnavailable("booking_service_invalid")
    if not all(callable(item) for item in
               (server_config_loader,payment_policy_loader,payment_evidence_loader)):
        raise BookingHttpCompositionUnavailable("booking_server_dependencies_missing")
    config=server_config_loader()
    if not isinstance(config,dict) or config.get("enabled") is not True:
        raise BookingHttpCompositionUnavailable("booking_server_not_qualified")
    policy=payment_policy_loader(payload["service"])
    evidence=payment_evidence_loader(payload["service"])
    trusted=customer_booking_trusted_route_context.build(
        service=payload["service"],server_config=config,
        payment_policy=policy,payment_evidence=evidence)
    return customer_booking_trusted_executor.execute,trusted
