"""Read-only qualification report for Mercure VL administrative metadata."""
from __future__ import annotations

REQUIRED=("centre_type","ligne_id","utilisateur","prestation","duree")


def assess(observed: object) -> dict:
    if not isinstance(observed,dict):
        raise ValueError("mercure_metadata_observation_invalid")
    counts={}
    missing=[]
    for field in REQUIRED:
        values=observed.get(field)
        if not isinstance(values,(list,tuple,set,frozenset)):
            raise ValueError("mercure_metadata_observation_invalid")
        if not all(isinstance(v,str) and v.isascii() and v.isdecimal() for v in values):
            raise ValueError("mercure_metadata_observation_invalid")
        counts[field]=len(values)
        if not values:
            missing.append(field)
    return {"qualified":not missing,"missingObservations":missing,
            "observedCounts":counts,"customerWriteEnabled":False}
