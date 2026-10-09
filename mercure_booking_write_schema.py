"""Observed read-only Mercure AJAX field contracts; never authorizes writes."""
from __future__ import annotations

VL_REQUIRED=frozenset({"centre_type","ligne_id","duree","client_compte",
    "nom","prenom","email","telephone","marque","modele","energie",
    "immatriculation","prestation","utilisateur","date","rendezvous_id","tcheckDispo"})
PL_REQUIRED=frozenset({"centre_type","ligne_id","duree_pl","nom_pl",
    "email_pl","telephone_pl","client_compte_pl","vehicule_client_pl",
    "prestation_pl","type_vehicule","utilisateur_pl","immatriculation_pl",
    "energie_pl","date","rendezvous_id","tcheckDispo"})


class MercureWriteSchemaError(ValueError):
    pass


def audit_fields(*, vehicle_class: str, observed: object) -> dict:
    if vehicle_class not in {"vl","pl"}:
        raise MercureWriteSchemaError("mercure_vehicle_class_invalid")
    if not isinstance(observed,(list,tuple,set,frozenset)) or len(observed)>100:
        raise MercureWriteSchemaError("mercure_write_fields_invalid")
    if not all(isinstance(field,str) and field.isidentifier() for field in observed):
        raise MercureWriteSchemaError("mercure_write_fields_invalid")
    required=VL_REQUIRED if vehicle_class=="vl" else PL_REQUIRED
    missing=sorted(required-set(observed))
    return {"vehicleClass":vehicle_class,"schemaObserved":not missing,
            "missingFields":missing,"customerWriteQualified":False}
