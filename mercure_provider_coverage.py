from __future__ import annotations

import datetime
import os
import re


HISTORY_START_ENV = "CYBERCHECK_MERCURE_DSAR_HISTORY_START"
FUTURE_DAYS_ENV = "CYBERCHECK_MERCURE_DSAR_FUTURE_DAYS"
EVIDENCE_SHA256_ENV = "CYBERCHECK_MERCURE_DSAR_COVERAGE_EVIDENCE_SHA256"
APPOINTMENT_SOURCE_ENV = "CYBERCHECK_MERCURE_DSAR_APPOINTMENT_INVENTORY_SOURCE"
APPOINTMENT_EVIDENCE_SHA256_ENV = "CYBERCHECK_MERCURE_DSAR_APPOINTMENT_INVENTORY_EVIDENCE_SHA256"
VEHICLE_SOURCE_ENV = "CYBERCHECK_MERCURE_DSAR_VEHICLE_INVENTORY_SOURCE"
VEHICLE_EVIDENCE_SHA256_ENV = "CYBERCHECK_MERCURE_DSAR_VEHICLE_INVENTORY_EVIDENCE_SHA256"
AUTHORITATIVE_APPOINTMENT_INVENTORY_SOURCE = "subject_bound_appointment_calendar"
AUTHORITATIVE_APPOINTMENT_SOURCE = "appointment_calendar_subject_vehicle_set"
MAX_FUTURE_DAYS = 3650
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def appointment_inventory_attestation() -> dict:
    """Return explicit evidence for the Mercure subject appointment inventory.

    The calendar endpoint is observable in CheckupAuto, but code observation alone
    cannot establish that it is the provider's exhaustive subject-level inventory.
    Completeness therefore requires an explicit provider/contract attestation of
    that exact source plus the SHA-256 of evidence stored outside Git and runtime
    responses. This prevents a temporal coverage declaration from silently being
    promoted into source-authority evidence.
    """
    source_raw = os.environ.get(APPOINTMENT_SOURCE_ENV, "").strip().lower()
    evidence_raw = os.environ.get(APPOINTMENT_EVIDENCE_SHA256_ENV, "").strip().lower()

    if not source_raw and not evidence_raw:
        return {
            "state": "unconfigured",
            "attested": False,
            "source": "",
            "evidenceSha256": "",
            "reason": "provider_appointment_inventory_not_attested",
        }
    if not source_raw or not evidence_raw:
        return {
            "state": "invalid",
            "attested": False,
            "source": "",
            "evidenceSha256": "",
            "reason": "provider_appointment_inventory_configuration_incomplete",
        }
    if source_raw != AUTHORITATIVE_APPOINTMENT_INVENTORY_SOURCE:
        return {
            "state": "invalid",
            "attested": False,
            "source": "",
            "evidenceSha256": "",
            "reason": "provider_appointment_inventory_source_unsupported",
        }
    if not _SHA256_RE.fullmatch(evidence_raw):
        return {
            "state": "invalid",
            "attested": False,
            "source": "",
            "evidenceSha256": "",
            "reason": "provider_appointment_inventory_evidence_hash_invalid",
        }
    return {
        "state": "attested",
        "attested": True,
        "source": AUTHORITATIVE_APPOINTMENT_INVENTORY_SOURCE,
        "evidenceSha256": evidence_raw,
        "reason": "",
    }


def vehicle_inventory_attestation() -> dict:
    """Return the independently attested Mercure subject-to-vehicle boundary.

    CheckupAuto currently discovers vehicle identifiers through subject-bound
    appointment calendar events before calling ``get-vehicule``. That observed
    path must not be promoted to an exhaustive client vehicle inventory merely
    because a temporal appointment boundary is attested. Completeness requires
    separate provider/contract evidence that this calendar relation is the
    authoritative complete subject-to-vehicle set. Only the evidence SHA-256 is
    exposed; the evidence body remains outside Git and runtime responses.
    """
    source_raw = os.environ.get(VEHICLE_SOURCE_ENV, "").strip().lower()
    evidence_raw = os.environ.get(VEHICLE_EVIDENCE_SHA256_ENV, "").strip().lower()

    if not source_raw and not evidence_raw:
        return {
            "state": "unconfigured",
            "attested": False,
            "source": "",
            "evidenceSha256": "",
            "reason": "provider_vehicle_inventory_not_attested",
        }
    if not source_raw or not evidence_raw:
        return {
            "state": "invalid",
            "attested": False,
            "source": "",
            "evidenceSha256": "",
            "reason": "provider_vehicle_inventory_configuration_incomplete",
        }
    if source_raw != AUTHORITATIVE_APPOINTMENT_SOURCE:
        return {
            "state": "invalid",
            "attested": False,
            "source": "",
            "evidenceSha256": "",
            "reason": "provider_vehicle_inventory_source_unsupported",
        }
    if not _SHA256_RE.fullmatch(evidence_raw):
        return {
            "state": "invalid",
            "attested": False,
            "source": "",
            "evidenceSha256": "",
            "reason": "provider_vehicle_inventory_evidence_hash_invalid",
        }
    return {
        "state": "attested",
        "attested": True,
        "source": AUTHORITATIVE_APPOINTMENT_SOURCE,
        "evidenceSha256": evidence_raw,
        "reason": "",
    }


def _invalid(reason: str) -> dict:
    return {
        "state": "invalid",
        "attested": False,
        "historyStart": "",
        "futureDays": 0,
        "evidenceSha256": "",
        "reason": reason,
        "appointmentInventory": appointment_inventory_attestation(),
        "vehicleInventory": vehicle_inventory_attestation(),
    }


def boundary(today: datetime.date | None = None) -> dict:
    """Return a non-secret provider coverage boundary attestation.

    CheckupAuto must not infer Mercure's historical or future data boundary from
    an empty query result. Completeness may only be considered after an operator
    configures a provider/contract-backed temporal boundary, explicit authority
    for the subject appointment inventory, and SHA-256 evidence for both. Vehicle
    inventory authority is attested independently and never inferred from
    appointments. Evidence bodies remain outside Git and runtime responses.
    """
    current = today or datetime.date.today()
    history_raw = os.environ.get(HISTORY_START_ENV, "").strip()
    future_raw = os.environ.get(FUTURE_DAYS_ENV, "").strip()
    evidence_raw = os.environ.get(EVIDENCE_SHA256_ENV, "").strip().lower()
    appointment_inventory = appointment_inventory_attestation()
    vehicle_inventory = vehicle_inventory_attestation()

    if not history_raw and not future_raw and not evidence_raw:
        return {
            "state": "unconfigured",
            "attested": False,
            "historyStart": "",
            "futureDays": 0,
            "evidenceSha256": "",
            "reason": "provider_boundary_not_attested",
            "appointmentInventory": appointment_inventory,
            "vehicleInventory": vehicle_inventory,
        }
    if not history_raw or not future_raw or not evidence_raw:
        return _invalid("provider_boundary_configuration_incomplete")

    try:
        history_start = datetime.date.fromisoformat(history_raw)
    except ValueError:
        return _invalid("provider_history_start_invalid")
    if history_start > current:
        return _invalid("provider_history_start_in_future")

    try:
        future_days = int(future_raw)
    except ValueError:
        return _invalid("provider_future_horizon_invalid")
    if future_days < 0 or future_days > MAX_FUTURE_DAYS:
        return _invalid("provider_future_horizon_out_of_range")
    if not _SHA256_RE.fullmatch(evidence_raw):
        return _invalid("provider_evidence_hash_invalid")

    if appointment_inventory.get("state") == "invalid":
        return _invalid(str(appointment_inventory.get("reason") or "provider_appointment_inventory_invalid"))
    if not appointment_inventory.get("attested"):
        return {
            "state": "unconfigured",
            "attested": False,
            "historyStart": history_start.isoformat(),
            "futureDays": future_days,
            "evidenceSha256": evidence_raw,
            "reason": "provider_appointment_inventory_not_attested",
            "appointmentInventory": appointment_inventory,
            "vehicleInventory": vehicle_inventory,
        }

    return {
        "state": "attested",
        "attested": True,
        "historyStart": history_start.isoformat(),
        "futureDays": future_days,
        "evidenceSha256": evidence_raw,
        "reason": "",
        "appointmentInventory": appointment_inventory,
        "vehicleInventory": vehicle_inventory,
    }


def capability() -> dict:
    return {
        "requiresExplicitProviderBoundary": True,
        "requiresAuthoritativeSourceEvidence": True,
        "requiresExternalEvidenceSha256": True,
        "requiresIndependentAppointmentInventoryEvidence": True,
        "appointmentInventoryAuthoritativeSource": AUTHORITATIVE_APPOINTMENT_INVENTORY_SOURCE,
        "requiresIndependentVehicleInventoryEvidence": True,
        "vehicleInventoryAuthoritativeSource": AUTHORITATIVE_APPOINTMENT_SOURCE,
        "rawEvidenceStoredInRepository": False,
        "emptyResultProvesHistoricalExhaustion": False,
        "calendarObservationProvesAppointmentExhaustion": False,
        "appointmentVehicleObservationProvesVehicleExhaustion": False,
        "maxConfiguredFutureDays": MAX_FUTURE_DAYS,
    }
