"""Capability gate for the legacy Mercure centre-side booking gateway.

Never treat MySQL schema access, an admin session or synthetic appointment
creation as authorization to write real customer appointments.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CentreGatewayEvidence:
    private_transport_verified: bool = False
    dedicated_least_privilege_identity: bool = False
    real_booking_operation_documented: bool = False
    customer_vehicle_mapping_verified: bool = False
    idempotent_write_verified: bool = False
    authoritative_reread_verified: bool = False
    rollback_and_recovery_verified: bool = False


REQUIRED = (
    "private_transport_verified",
    "dedicated_least_privilege_identity",
    "real_booking_operation_documented",
    "customer_vehicle_mapping_verified",
    "idempotent_write_verified",
    "authoritative_reread_verified",
    "rollback_and_recovery_verified",
)


def qualification(evidence: CentreGatewayEvidence) -> dict:
    if not isinstance(evidence,CentreGatewayEvidence):
        raise ValueError("centre_gateway_evidence_invalid")
    missing=[field for field in REQUIRED if getattr(evidence,field) is not True]
    return {"qualified":not missing,"realBookingEnabled":False,"missing":missing,
            "legacyDatabaseDirectWriteAllowed":False,
            "syntheticWriterAllowedForCustomers":False}
