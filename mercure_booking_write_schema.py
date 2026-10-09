"""Read-only Mercure light-vehicle booking contract; heavy vehicles excluded."""
from __future__ import annotations

VL_REQUIRED=frozenset({"centre_type","ligne_id","duree","client_compte",
    "nom","prenom","email","telephone","marque","modele","energie",
    "immatriculation","prestation","utilisateur","date","rendezvous_id","tcheckDispo"})

class MercureWriteSchemaError(ValueError):
    pass


def audit_fields(*, vehicle_class: str, observed: object) -> dict:
    if vehicle_class != "vl":
        raise MercureWriteSchemaError("mercure_vehicle_class_invalid")
    if not isinstance(observed,(list,tuple,set,frozenset)) or len(observed)>100:
        raise MercureWriteSchemaError("mercure_write_fields_invalid")
    if not all(isinstance(field,str) and field.isidentifier() for field in observed):
        raise MercureWriteSchemaError("mercure_write_fields_invalid")
    required=VL_REQUIRED
    missing=sorted(required-set(observed))
    return {"vehicleClass":vehicle_class,"schemaObserved":not missing,
            "missingFields":missing,"customerWriteQualified":False}
