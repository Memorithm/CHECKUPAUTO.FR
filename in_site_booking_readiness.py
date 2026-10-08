"""Safety gate for on-site reservation confirmation; no real customer writes."""
from dataclasses import dataclass


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


def declared_capabilities() -> BookingCapabilities:
    """The existing synthetic Mercure test writer is NOT a live booking API."""
    return BookingCapabilities()
