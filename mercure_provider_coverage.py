from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
import re
import tempfile


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
PRIVATE_SCHEMA = "checkupauto.mercure-provider-coverage/v1"
PRIVATE_FILENAME = "mercure-provider-coverage.json"
CONFIRM_BOUNDARY = "PROVIDER-BOUNDARY-EVIDENCE-REVIEWED"
CONFIRM_APPOINTMENT = "PROVIDER-APPOINTMENT-INVENTORY-EVIDENCE-REVIEWED"
CONFIRM_VEHICLE = "PROVIDER-VEHICLE-INVENTORY-EVIDENCE-REVIEWED"

_CONFIG_ENV = {
    "historyStart": HISTORY_START_ENV,
    "futureDays": FUTURE_DAYS_ENV,
    "evidenceSha256": EVIDENCE_SHA256_ENV,
    "appointmentSource": APPOINTMENT_SOURCE_ENV,
    "appointmentEvidenceSha256": APPOINTMENT_EVIDENCE_SHA256_ENV,
    "vehicleSource": VEHICLE_SOURCE_ENV,
    "vehicleEvidenceSha256": VEHICLE_EVIDENCE_SHA256_ENV,
}


def _private_dir() -> Path:
    return Path(
        os.environ.get("CYBERCHECK_PRIVATE_DIR", "/root/CyberCheckPrivate")
    ).expanduser()


def _private_path() -> Path:
    return _private_dir() / "integrations" / PRIVATE_FILENAME


def _private_exists() -> bool:
    path = _private_path()
    try:
        return path.exists()
    except PermissionError as exc:
        if not str(os.environ.get("CYBERCHECK_PRIVATE_DIR") or "").strip():
            return False
        raise RuntimeError("configuration Mercure privée inaccessible") from exc


def _load_private_payload() -> dict | None:
    path = _private_path()
    if not _private_exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("configuration Mercure privée invalide")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError("configuration Mercure privée invalide") from exc
    if not isinstance(payload, dict) or payload.get("schema") != PRIVATE_SCHEMA:
        raise RuntimeError("configuration Mercure privée invalide")
    required = {
        "schema",
        "historyStart",
        "futureDays",
        "evidenceSha256",
        "appointmentSource",
        "appointmentEvidenceSha256",
        "vehicleSource",
        "vehicleEvidenceSha256",
    }
    if set(payload) != required:
        raise RuntimeError("configuration Mercure privée invalide")
    return payload


def _environment_values() -> dict:
    return {
        key: str(os.environ.get(env_name) or "").strip()
        for key, env_name in _CONFIG_ENV.items()
    }


def _configuration() -> tuple[str, dict]:
    environment = _environment_values()
    if any(environment.values()):
        return "environment", environment
    try:
        private = _load_private_payload()
    except RuntimeError:
        return "invalid_private", {key: "" for key in _CONFIG_ENV}
    if private is None:
        return "none", {key: "" for key in _CONFIG_ENV}
    return "private", {
        key: str(private.get(key) or "").strip()
        for key in _CONFIG_ENV
    }


def _ensure_private_dir() -> Path:
    root = _private_path().parent
    if root.exists() and root.is_symlink():
        raise RuntimeError("répertoire Mercure privé invalide")
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(0o700)
    return root


def _validated_hash(value: object, name: str, *, required: bool = True) -> str:
    digest = str(value or "").strip().lower()
    if not digest and not required:
        return ""
    if not _SHA256_RE.fullmatch(digest):
        raise ValueError(f"{name} invalide")
    return digest


def _validated_private_payload(payload: object, today: datetime.date | None = None) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("configuration Mercure invalide")
    allowed = {
        "historyStart",
        "futureDays",
        "evidenceSha256",
        "appointmentEvidenceSha256",
        "vehicleEvidenceSha256",
        "confirmBoundary",
        "confirmAppointment",
        "confirmVehicle",
    }
    if set(payload) != allowed:
        raise ValueError("configuration Mercure invalide")
    if str(payload.get("confirmBoundary") or "") != CONFIRM_BOUNDARY:
        raise PermissionError("confirmation frontière fournisseur requise")
    if str(payload.get("confirmAppointment") or "") != CONFIRM_APPOINTMENT:
        raise PermissionError("confirmation inventaire rendez-vous requise")

    current = today or datetime.date.today()
    try:
        history = datetime.date.fromisoformat(str(payload.get("historyStart") or "").strip())
    except ValueError as exc:
        raise ValueError("date historique fournisseur invalide") from exc
    if history > current:
        raise ValueError("date historique fournisseur future")

    try:
        future_days = int(payload.get("futureDays"))
    except (TypeError, ValueError) as exc:
        raise ValueError("horizon fournisseur invalide") from exc
    if future_days < 0 or future_days > MAX_FUTURE_DAYS:
        raise ValueError("horizon fournisseur invalide")

    temporal_hash = _validated_hash(payload.get("evidenceSha256"), "preuve temporelle")
    appointment_hash = _validated_hash(
        payload.get("appointmentEvidenceSha256"),
        "preuve inventaire rendez-vous",
    )
    vehicle_hash = _validated_hash(
        payload.get("vehicleEvidenceSha256"),
        "preuve inventaire véhicules",
        required=False,
    )
    if vehicle_hash and str(payload.get("confirmVehicle") or "") != CONFIRM_VEHICLE:
        raise PermissionError("confirmation inventaire véhicules requise")

    return {
        "schema": PRIVATE_SCHEMA,
        "historyStart": history.isoformat(),
        "futureDays": str(future_days),
        "evidenceSha256": temporal_hash,
        "appointmentSource": AUTHORITATIVE_APPOINTMENT_INVENTORY_SOURCE,
        "appointmentEvidenceSha256": appointment_hash,
        "vehicleSource": AUTHORITATIVE_APPOINTMENT_SOURCE if vehicle_hash else "",
        "vehicleEvidenceSha256": vehicle_hash,
    }


def save_private_configuration(payload: object) -> dict:
    if any(_environment_values().values()):
        raise RuntimeError("configuration Mercure pilotée par environnement")
    data = _validated_private_payload(payload)
    root = _ensure_private_dir()
    target = _private_path()
    if target.exists() and (target.is_symlink() or not target.is_file()):
        raise RuntimeError("configuration Mercure privée invalide")
    fd, temporary = tempfile.mkstemp(
        prefix=".mercure-provider-coverage-",
        suffix=".json",
        dir=root,
    )
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        target.chmod(0o600)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return configuration_info()


def delete_private_configuration() -> dict:
    if any(_environment_values().values()):
        raise RuntimeError("configuration Mercure pilotée par environnement")
    path = _private_path()
    if path.is_symlink():
        raise RuntimeError("configuration Mercure privée invalide")
    if path.exists() and not path.is_file():
        raise RuntimeError("configuration Mercure privée invalide")
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    return configuration_info()


def appointment_inventory_attestation() -> dict:
    """Return explicit evidence for the Mercure subject appointment inventory.

    The calendar endpoint is observable in CheckupAuto, but code observation alone
    cannot establish that it is the provider's exhaustive subject-level inventory.
    Completeness therefore requires an explicit provider/contract attestation of
    that exact source plus the SHA-256 of evidence stored outside Git and runtime
    responses. This prevents a temporal coverage declaration from silently being
    promoted into source-authority evidence.
    """
    source_kind, values = _configuration()
    if source_kind == "invalid_private":
        return {
            "state": "invalid",
            "attested": False,
            "source": "",
            "evidenceSha256": "",
            "reason": "provider_private_configuration_invalid",
        }
    source_raw = str(values.get("appointmentSource") or "").strip().lower()
    evidence_raw = str(values.get("appointmentEvidenceSha256") or "").strip().lower()

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
    source_kind, values = _configuration()
    if source_kind == "invalid_private":
        return {
            "state": "invalid",
            "attested": False,
            "source": "",
            "evidenceSha256": "",
            "reason": "provider_private_configuration_invalid",
        }
    source_raw = str(values.get("vehicleSource") or "").strip().lower()
    evidence_raw = str(values.get("vehicleEvidenceSha256") or "").strip().lower()

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
    source_kind, values = _configuration()
    if source_kind == "invalid_private":
        return _invalid("provider_private_configuration_invalid")
    history_raw = str(values.get("historyStart") or "").strip()
    future_raw = str(values.get("futureDays") or "").strip()
    evidence_raw = str(values.get("evidenceSha256") or "").strip().lower()
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


def configuration_info() -> dict:
    source_kind, _ = _configuration()
    source = (
        "private"
        if source_kind in {"private", "invalid_private"}
        else source_kind
    )
    state = boundary()
    return {
        "configured": source_kind not in {"none", "invalid_private"},
        "source": source,
        "editable": source_kind != "environment",
        "boundary": state,
        "appointmentAuthoritativeSource": AUTHORITATIVE_APPOINTMENT_INVENTORY_SOURCE,
        "vehicleAuthoritativeSource": AUTHORITATIVE_APPOINTMENT_SOURCE,
        "rawEvidenceStored": False,
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
