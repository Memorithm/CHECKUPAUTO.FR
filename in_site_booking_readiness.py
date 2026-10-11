"""Safety gate for on-site reservation confirmation; no real customer writes.

Capabilities are derived from configuration and from a signed, unexpired
production sign-off (see ``booking_signoff_evidence``).  With the default
configuration, or without valid evidence, every capability is False.
"""
import os
from dataclasses import dataclass

import booking_signoff_evidence
import customer_booking_server_config_source

IN_SITE_FLAG_ENV = "CHECKUPAUTO_IN_SITE_BOOKING_ENABLED"


@dataclass(frozen=True)
class BookingCapabilities:
    authenticated_customer: bool = False
    validated_vehicle: bool = False
    authoritative_slot: bool = False
    real_mercure_write_qualified: bool = False
    idempotent_reconciliation_qualified: bool = False
    payment_required: bool = False
    embedded_payment_qualified: bool = False
    payment_result_verified: bool = False
    appointment_verified: bool = False


def evaluate(capabilities: BookingCapabilities) -> dict:
    missing = [
        label for field, label in (
            ("authenticated_customer", "customer_authentication_required"),
            ("validated_vehicle", "vehicle_validation_required"),
            ("authoritative_slot", "authoritative_slot_required"),
            ("real_mercure_write_qualified", "real_mercure_booking_connector_unqualified"),
            ("idempotent_reconciliation_qualified", "booking_reconciliation_unqualified"),
            ("appointment_verified", "mercure_appointment_not_verified"),
        ) if not getattr(capabilities, field)
    ]
    if capabilities.payment_required:
        if not capabilities.embedded_payment_qualified:
            missing.append("embedded_mercure_payment_unqualified")
        if not capabilities.payment_result_verified:
            missing.append("payment_not_verified")
    return {
        "ready": not missing,
        "confirmed": not missing,
        "missing": missing,
        "paymentRequired": capabilities.payment_required,
        "bookingOnSite": True,
    }


def in_site_flag_enabled(environ=None) -> bool:
    source = os.environ if environ is None else environ
    return str(source.get(IN_SITE_FLAG_ENV, "")).strip() == "true"


def activation_state(environ=None, now=None) -> dict:
    """Configuration and evidence facts; codes only, never secrets or paths."""
    flag = in_site_flag_enabled(environ)
    try:
        server = customer_booking_server_config_source.load(environ=environ)
        write = server.get("enabled") is True
    except customer_booking_server_config_source.BookingServerConfigError:
        server, write = {}, False
    if flag and write:
        signoff = booking_signoff_evidence.status(
            line_id=server["lineId"], operator_id=server["operatorId"],
            environ=environ, now=now)
    else:
        signoff = {"valid": False, "reason": "booking_signoff_not_evaluated"}
    return {"inSiteFlag": flag, "providerWriteEnabled": write,
            "signoffValid": signoff.get("valid") is True,
            "signoffReason": str(signoff.get("reason") or "")}


def declared_capabilities(environ=None, now=None) -> BookingCapabilities:
    """The synthetic Mercure test writer is NOT a live booking API.

    Only the explicit on-site flag, an enabled provider-write configuration and a
    valid signed sign-off together qualify the customer booking capabilities.
    Payment capabilities stay False: the per-request payment policy gate
    (``customer_booking_payment_policy``) still refuses unverified online payment.
    """
    state = activation_state(environ, now)
    if not (state["inSiteFlag"] and state["providerWriteEnabled"] and state["signoffValid"]):
        return BookingCapabilities()
    return BookingCapabilities(
        authenticated_customer=True, validated_vehicle=True,
        authoritative_slot=True, real_mercure_write_qualified=True,
        idempotent_reconciliation_qualified=True, appointment_verified=True,
    )


def public_status(environ=None, now=None) -> dict:
    """Expose non-sensitive qualification facts, never credentials or customer data."""
    current = evaluate(declared_capabilities(environ, now))
    return {
        "ok": True,
        "bookingOnSiteRequired": True,
        "bookingEnabled": current["ready"],
        "confirmationEnabled": current["confirmed"],
        "blockers": current["missing"],
        "syntheticAppointmentsAreProduction": False,
        "externalMercureRedirectAllowed": False,
    }
