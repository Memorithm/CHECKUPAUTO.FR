"""Bind independently observed provider metadata to a VL appointment payload."""
from __future__ import annotations
from mercure_vl_write_payload import build

FIELDS=("centre_type","ligne_id","utilisateur","prestation","duree")


def prepare(*, appointment: dict, metadata: dict, observed: dict) -> dict:
    if not isinstance(metadata,dict) or set(metadata)!=set(FIELDS):
        raise ValueError("mercure_vl_metadata_incomplete")
    if not isinstance(observed,dict):
        raise ValueError("mercure_vl_metadata_unverified")
    for key in FIELDS:
        choices=observed.get(key)
        if not isinstance(choices,(list,tuple,set,frozenset)) or metadata[key] not in choices:
            raise ValueError("mercure_vl_metadata_unverified")
    return build(appointment=appointment,service_id=metadata["prestation"],
                 duration=metadata["duree"],centre_type=metadata["centre_type"],
                 line_id=metadata["ligne_id"],operator_id=metadata["utilisateur"])
