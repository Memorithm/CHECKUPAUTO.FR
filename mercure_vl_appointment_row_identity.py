"""Read-only identity mapping from the observed Mercure appointment list schema."""
from __future__ import annotations
from mercure_vl_provider_identity_reader import verify_record


class MercureAppointmentRowError(ValueError):
    pass


def verify(*, row: object, reference: str, account_id: str, vehicle_id: str,
           service: str, registration: str, expected_service_label: str):
    if not isinstance(row,dict):
        raise MercureAppointmentRowError("mercure_appointment_row_invalid")
    actual={
        "id":str(row.get("id") or ""),
        "immatriculation":str(row.get("immat") or "").strip().upper(),
        "prestation_id":str(row.get("prestation") or "").strip(),
        "independentRead":True,
    }
    # The administrative list exposes a service label, not a provider service ID.
    # A separately qualified label must be supplied; never invent an ID.
    if actual["prestation_id"]!=expected_service_label:
        raise MercureAppointmentRowError("mercure_service_label_mismatch")
    return verify_record(
        record=actual,provider_reference=reference,account_id=account_id,
        vehicle_id=vehicle_id,service=service,registration=registration,
        expected_provider_service=expected_service_label)
