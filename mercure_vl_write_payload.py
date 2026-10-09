"""VL-only Mercure payload construction. Does not perform provider writes."""
from __future__ import annotations

import re

from mercure_booking_write_schema import VL_REQUIRED,audit_fields


class MercureVlWritePayloadError(ValueError):
    pass


def build(*, appointment: dict, service_id: str, duration: str,
          centre_type: str, line_id: str, operator_id: str) -> dict:
    if not isinstance(appointment,dict):
        raise MercureVlWritePayloadError("mercure_vl_appointment_invalid")
    for value in (service_id,duration,centre_type,line_id,operator_id):
        if not isinstance(value,str) or not re.fullmatch(r"[0-9]{1,12}",value):
            raise MercureVlWritePayloadError("mercure_vl_provider_metadata_unqualified")
    if centre_type not in {"1","4"}:
        raise MercureVlWritePayloadError("mercure_vl_centre_type_invalid")
    required=("nom","prenom","email","telephone","marque","modele",
              "energie","immatriculation","date")
    if not all(isinstance(appointment.get(key),str) and appointment[key].strip() for key in required):
        raise MercureVlWritePayloadError("mercure_vl_customer_payload_incomplete")
    payload={
        "centre_type":centre_type,"ligne_id":line_id,"duree":duration,
        "client_compte":"","nom":appointment["nom"],"prenom":appointment["prenom"],
        "email":appointment["email"],"telephone":appointment["telephone"],
        "marque":appointment["marque"],"modele":appointment["modele"],
        "energie":appointment["energie"],"immatriculation":appointment["immatriculation"],
        "prestation":service_id,"utilisateur":operator_id,"date":appointment["date"],
        "rendezvous_id":"","tcheckDispo":"true",
    }
    if not audit_fields(vehicle_class="vl",observed=set(payload))["schemaObserved"]:
        raise MercureVlWritePayloadError("mercure_vl_schema_incomplete")
    return payload
