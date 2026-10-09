"""Read-only VL booking dry run. Never sends an appointment to Mercure."""
from __future__ import annotations

from mercure_booking_write_schema import VL_REQUIRED,audit_fields
from mercure_customer_booking_assembly import assemble
from mercure_booking_write_contract import BookingWriteRequest


class MercureVlDryRunError(ValueError):
    pass


def prepare(*, request: BookingWriteRequest, account: dict, vehicle: dict,
            observed_form_fields: object) -> dict:
    schema=audit_fields(vehicle_class="vl",observed=observed_form_fields)
    if not schema["schemaObserved"]:
        raise MercureVlDryRunError("mercure_vl_form_schema_incomplete")
    assembled=assemble(request=request,account=account,vehicle=vehicle)
    if assembled.get("providerWritePerformed") is not False:
        raise MercureVlDryRunError("mercure_vl_write_state_invalid")
    appointment=assembled["appointment"]
    if not all(appointment.get(key) for key in
               ("nom","prenom","email","telephone","marque","modele",
                "energie","immatriculation","date")):
        raise MercureVlDryRunError("mercure_vl_payload_incomplete")
    return {"readyForProviderQualification":True,
            "customerWriteQualified":False,"providerWritePerformed":False,
            "bookingConfirmed":False,"vehicleClass":"vl",
            "schemaFieldCount":len(VL_REQUIRED)}
