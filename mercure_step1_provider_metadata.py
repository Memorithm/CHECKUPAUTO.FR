"""Fail-closed qualification of VL provider metadata from independently observed options."""
import re

FIELDS=("centre_type","ligne_id","utilisateur","prestation","duree")

def qualify(metadata, observed):
    if not isinstance(metadata,dict) or not isinstance(observed,dict):
        raise ValueError("mercure_metadata_missing")
    if set(metadata)!=set(FIELDS):
        raise ValueError("mercure_metadata_incomplete")
    for key in FIELDS:
        value=metadata[key]
        choices=observed.get(key)
        if not isinstance(value,str) or not re.fullmatch(r"[0-9]{1,12}",value):
            raise ValueError("mercure_metadata_invalid")
        if not isinstance(choices,(tuple,list,set,frozenset)) or value not in choices:
            raise ValueError("mercure_metadata_unverified")
    if metadata["centre_type"] not in {"1","4"}:
        raise ValueError("mercure_not_vl")
    return dict(metadata)
